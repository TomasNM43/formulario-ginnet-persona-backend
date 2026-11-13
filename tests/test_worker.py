import threading
from datetime import datetime, timedelta

import worker
from app.models import persona_audio_table
from sqlalchemy import insert, select, update

T = persona_audio_table("main")


def add(engine, tag, estado="pendiente", created=None, inicio=None, ref="", test=""):
    with engine.begin() as c:
        return c.execute(
            insert(T)
            .values(TAG=tag, ESTADO=estado, FECHA_CREACION=created or datetime.now(), FECHA_INICIO=inicio,
                    RUTA_REFERENCIA=ref, RUTA_PRUEBA=test)
            .returning(T.c.ID_PERSONA_AUDIO)
        ).scalar_one()


def estado(engine, id_):
    with engine.connect() as c:
        return c.execute(select(T.c.ESTADO, T.c.ERROR_MSG, T.c.FECHA_INICIO).where(T.c.ID_PERSONA_AUDIO == id_)).one()


def test_claims_oldest_first(engine):
    now = datetime.now()
    new = add(engine, "new", created=now)
    old = add(engine, "old", created=now - timedelta(hours=1))
    job = worker.claim_next(engine, "main")
    assert job and job.id == old
    row = estado(engine, old)
    assert row.ESTADO == "procesando" and row.FECHA_INICIO is not None
    assert estado(engine, new).ESTADO == "pendiente"
    assert worker.claim_next(engine, "main").id == new
    assert worker.claim_next(engine, "main") is None


def test_lost_race_retries_next(engine, monkeypatch):
    a = add(engine, "a", created=datetime.now() - timedelta(hours=2))
    b = add(engine, "b", created=datetime.now() - timedelta(hours=1))
    real = worker.update
    state = {"stolen": False}

    def sneaky(table):
        # Otro worker toma 'a' justo antes de nuestro UPDATE
        if not state["stolen"]:
            state["stolen"] = True
            with engine.begin() as c:
                c.execute(real(table).where(table.c.ID_PERSONA_AUDIO == a).values(ESTADO="procesando"))
        return real(table)

    monkeypatch.setattr(worker, "update", sneaky)
    job = worker.claim_next(engine, "main")
    assert job and job.id == b


def test_concurrent_workers_claim_distinct_jobs(tmp_path):
    # SQLite en archivo para tener conexiones reales independientes
    from sqlalchemy import create_engine, event

    eng = create_engine(f"sqlite:///{tmp_path / 'q.db'}", connect_args={"timeout": 30, "check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _f(c, _r):
        c.create_function("systimestamp", 0, lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"))

    T.metadata.create_all(eng)
    ids = {add(eng, f"t{i}", created=datetime.now() + timedelta(seconds=i)) for i in range(10)}
    got: list[int] = []
    lock = threading.Lock()

    def run():
        while (j := worker.claim_next(eng, "main")) is not None:
            with lock:
                got.append(j.id)

    ts = [threading.Thread(target=run) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(got) == sorted(ids)  # ninguno repetido ni perdido


def test_run_one_success_and_error(engine, tmp_path):
    r, p = tmp_path / "r.wav", tmp_path / "p.wav"
    r.write_bytes(b"x")
    p.write_bytes(b"x")
    ok = add(engine, "ok", ref=str(r), test=str(p))
    assert worker.run_one(engine, "main") and estado(engine, ok).ESTADO == "listo"
    bad = add(engine, "bad", ref=str(r), test=str(tmp_path / "falta.wav"))
    assert worker.run_one(engine, "main")
    row = estado(engine, bad)
    assert row.ESTADO == "error" and row.ERROR_MSG
    assert not worker.run_one(engine, "main")


def test_error_message_truncated_to_1000_bytes():
    assert len(worker.truncate_bytes("ñ" * 900).encode()) <= 1000
    assert worker.truncate_bytes("ñ" * 900).encode().decode()  # sin cortar a mitad de carácter


def test_oracle_sql_shape():
    from sqlalchemy.dialects import oracle

    t = persona_audio_table("GINNET_AUDIO")
    d = oracle.dialect()
    sql = str(update(t).where(t.c.FECHA_INICIO < worker._stuck_cutoff(15)).values(FECHA_INICIO=worker.sys_timestamp()).compile(dialect=d))
    assert "SYSTIMESTAMP - numtodsinterval(:numtodsinterval_1, 'MINUTE')" in sql and "systimestamp()" not in sql
    q = str(select(t.c.TAG).order_by(t.c.FECHA_CREACION).limit(1).compile(dialect=d))
    assert "FETCH FIRST" in q and "LIMIT" not in q


def test_requeue_stuck(engine, monkeypatch):
    monkeypatch.setattr(worker, "_stuck_cutoff", lambda m: datetime.now() - timedelta(minutes=m))
    stuck = add(engine, "s", "procesando", inicio=datetime.now() - timedelta(minutes=30))
    fresh = add(engine, "f", "procesando", inicio=datetime.now() - timedelta(minutes=1))
    assert worker.requeue_stuck(engine, "main", 15) == 1
    assert estado(engine, stuck).ESTADO == "pendiente"
    assert estado(engine, fresh).ESTADO == "procesando"
