from datetime import timedelta

from sqlalchemy import select

from app import config, report_chat, service
from app.models import Alert, TableObservation

from .conftest import T0, login


def test_bill_check_waits_for_fresh_vacancy_and_payment_resolves_it(db, world):
    table = world["tables"]["T5"]
    camera = world["camera"]
    camera.status = "online"
    service.open_table_bill(db, table)
    bill = db.scalar(select(service.TableBill).where(service.TableBill.table_id == table.id))
    bill.opened_at = T0
    delay = timedelta(seconds=config.BILL_CHECK_GRACE_S)
    camera.last_heartbeat_at = T0 + delay
    evidence = TableObservation(table_id=table.id, restaurant_id=table.restaurant_id,
                                camera_id=camera.id, vacant_since=T0, observed_at=T0 + delay)
    db.add(evidence)
    db.commit()
    checks = select(Alert).where(Alert.table_id == table.id, Alert.type == "bill_check")
    service.sweep(db, T0 + delay - timedelta(seconds=1))
    assert db.scalar(checks) is None
    service.sweep(db, T0 + delay)
    service.sweep(db, T0 + delay + timedelta(seconds=1))
    alert = db.scalars(checks).one()
    service.mark_table_bill_paid(db, table, T0 + delay + timedelta(seconds=2))
    assert alert.status == "resolved"


def test_chat_history_saves_answer(client, world, monkeypatch):
    login(client, "admin@demo.test", "demo-admin")
    monkeypatch.setattr(report_chat, "answer", lambda question, report: "Saved answer")
    path = f"/v1/restaurants/{world['restaurant'].id}/analytics/chat"
    response = client.post(path, json={"question": "How busy?", "period": "week"})
    assert response.status_code == 200
    history = client.get(path).json()
    assert history[0]["answer"] == "Saved answer"
    assert history[0]["question"] == "How busy?"


def test_healthy_edge_heartbeat_records_tableware_and_resets_vacancy_on_return(db, world):
    table = world["tables"]["T5"]
    camera = world["camera"]
    restaurant = world["restaurant"]
    camera.status = "online"
    db.commit()
    for delta, present in [(5, False), (20, True)]:
        at = T0 + timedelta(seconds=delta)
        service.heartbeat(db, restaurant, camera, [{
            "table_id": table.id, "occupied": present, "people_present": present, "tableware_count": 2,
        }], at, at)
        observation = db.get(TableObservation, table.id)
        assert observation.tableware_count == 2
        assert observation.vacant_since == (None if present else at)


def test_chat_summary_works_without_gemini_and_is_saved(client, world, monkeypatch):
    login(client, "admin@demo.test", "demo-admin")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    path = f"/v1/restaurants/{world['restaurant'].id}/analytics/chat"
    response = client.post(path, json={"question": "Summarize this month", "period": "month", "mode": "summary"})
    assert response.status_code == 200
    assert "Monthly summary" in response.json()["answer"]
    assert client.get(path).json()[0]["mode"] == "summary"
