"""删除模型时的引用校验测试。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.exceptions import BusinessError
from app.services.model_service import ModelService


def test_delete_model_blocked_when_referenced(monkeypatch: pytest.MonkeyPatch) -> None:
    db = MagicMock()
    # scalar 依次返回：会话数、知识库数
    db.scalar.side_effect = [2, 1]
    svc = ModelService(db)

    row = SimpleNamespace(id=9, scope="private", user_id="u1")
    monkeypatch.setattr(svc, "_get_editable_row", lambda _id: row)
    monkeypatch.setattr(
        "app.services.model_service.get_current_user_id",
        lambda: "u1",
    )

    with pytest.raises(BusinessError, match="仍被引用"):
        svc.delete_model(9)

    db.delete.assert_not_called()
    db.commit.assert_not_called()


def test_delete_model_ok_when_unreferenced(monkeypatch: pytest.MonkeyPatch) -> None:
    db = MagicMock()
    db.scalar.side_effect = [0, 0]
    svc = ModelService(db)

    row = SimpleNamespace(id=9, scope="private", user_id="u1")
    monkeypatch.setattr(svc, "_get_editable_row", lambda _id: row)
    monkeypatch.setattr(svc, "_invalidate_public_cache", lambda _row: None)

    svc.delete_model(9)

    db.delete.assert_called_once_with(row)
    db.commit.assert_called_once()
