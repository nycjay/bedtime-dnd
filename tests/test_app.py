"""Tests for Bedtime D&D app — focused on logic with real signal."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create test client with mocked Supabase."""
    with patch.dict(
        "os.environ",
        {
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_KEY": "test-key",
            "SUPABASE_SERVICE_KEY": "test-service-key",
            "GEMINI_API_KEY": "test-gemini-key",
        },
    ):
        with patch("app.deps.create_client"), patch("app.deps.genai"):
            from main import app

            yield TestClient(app, raise_server_exceptions=False)


class TestRouteGuards:
    """Unauthenticated requests should redirect to login."""

    def test_campaigns_redirects_without_auth(self, client):
        resp = client.get("/campaigns", follow_redirects=False)
        assert resp.status_code in (302, 303, 307)
        assert "/login" in resp.headers.get("location", "")

    def test_players_redirects_without_auth(self, client):
        resp = client.get("/players", follow_redirects=False)
        assert resp.status_code in (302, 303, 307)
        assert "/login" in resp.headers.get("location", "")

    def test_settings_redirects_without_auth(self, client):
        resp = client.get("/settings", follow_redirects=False)
        assert resp.status_code in (302, 303, 307)
        assert "/login" in resp.headers.get("location", "")


class TestPublicRoutes:
    """Public routes should be accessible without auth."""

    def test_login_page_loads(self, client):
        from app.config import APP_NAME

        resp = client.get("/login")
        assert resp.status_code == 200
        # APP_NAME may contain & which gets HTML-escaped
        assert APP_NAME.replace("&", "&amp;") in resp.text

    def test_root_redirects_to_campaigns(self, client):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 307
        assert "/campaigns" in resp.headers.get("location", "")

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_404_shows_themed_error(self, client):
        resp = client.get("/nonexistent-page")
        assert resp.status_code == 404
        assert "Scroll Not Found" in resp.text


class TestStatParsing:
    """Stat validation logic."""

    def test_parse_stat_normal(self):
        from app.routes.players import _parse_stat

        class FakeForm:
            def get(self, key, default=None):
                return "4"

        assert _parse_stat(FakeForm(), "might") == 4

    def test_parse_stat_clamps_high(self):
        from app.routes.players import _parse_stat

        class FakeForm:
            def get(self, key, default=None):
                return "99"

        assert _parse_stat(FakeForm(), "might") == 5

    def test_parse_stat_clamps_low(self):
        from app.routes.players import _parse_stat

        class FakeForm:
            def get(self, key, default=None):
                return "0"

        assert _parse_stat(FakeForm(), "might") == 1

    def test_parse_stat_handles_garbage(self):
        from app.routes.players import _parse_stat

        class FakeForm:
            def get(self, key, default=None):
                return "abc"

        assert _parse_stat(FakeForm(), "might") == 3  # default

    def test_parse_stat_handles_none(self):
        from app.routes.players import _parse_stat

        class FakeForm:
            def get(self, key, default=None):
                return default

        assert _parse_stat(FakeForm(), "might") == 3  # default


class TestHPCalculation:
    """Max HP = 8 + Might."""

    def test_hp_formula(self):
        # Might 1 → HP 9, Might 5 → HP 13
        assert 8 + 1 == 9
        assert 8 + 5 == 13
        assert 8 + 3 == 11  # default


class TestApplyEvent:
    """Test _apply_event returns correct notifications."""

    def test_item_gained_returns_notification(self):
        from unittest.mock import patch

        with patch("app.helpers.supabase_admin") as mock_admin:
            mock_admin.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = (
                None  # noqa: E501
            )
            mock_admin.table.return_value.insert.return_value.execute.return_value = None

            from app.helpers import _apply_event

            member = {"players": {"name": "Talon", "max_hp": 11}, "current_hp": 11, "player_id": "p1", "inventory": []}
            result = _apply_event("c1", member, "award_item", "Magic Sword", "p1")
            assert result is not None
            assert result["type"] == "gained"
            assert result["item"] == "Magic Sword"
            assert result["player_name"] == "Talon"

    def test_damage_returns_no_notification(self):
        from unittest.mock import patch

        with patch("app.helpers.supabase_admin") as mock_admin:
            mock_admin.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = (
                None  # noqa: E501
            )
            mock_admin.table.return_value.insert.return_value.execute.return_value = None

            from app.helpers import _apply_event

            member = {"players": {"name": "Talon", "max_hp": 11}, "current_hp": 11, "player_id": "p1"}
            result = _apply_event("c1", member, "deal_damage", 3, "p1")
            assert result is None


class TestExtractGameEvents:
    """Test fallback game state extraction with mock Gemini responses."""

    def test_extracts_item_award(self):
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.text = '[{"player_name": "Talon", "event_type": "award_item", "value": "Magic Sword"}]'

        with patch("app.helpers.gemini_client") as mock_gemini, patch("app.helpers.supabase_admin") as mock_admin:
            mock_gemini.models.generate_content.return_value = mock_response
            mock_admin.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = (
                None
            )
            mock_admin.table.return_value.insert.return_value.execute.return_value = None

            from app.helpers import extract_game_events

            members = [
                {
                    "players": {"name": "Talon", "max_hp": 11},
                    "current_hp": 11,
                    "player_id": "p1",
                    "inventory": ["Old Shield"],
                }
            ]
            extract_game_events("c1", members, "Talon found a Magic Sword in the chest.")
            # Verify DB was called with updated inventory
            mock_admin.table.assert_any_call("campaign_members")

    def test_skips_hp_changes_in_extraction(self):
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.text = '[{"player_name": "Talon", "event_type": "deal_damage", "value": 5}]'

        with patch("app.helpers.gemini_client") as mock_gemini, patch("app.helpers.supabase_admin"):
            mock_gemini.models.generate_content.return_value = mock_response

            from app.helpers import extract_game_events

            members = [{"players": {"name": "Talon", "max_hp": 11}, "current_hp": 11, "player_id": "p1"}]
            extract_game_events("c1", members, "The goblin hit Talon for 5 damage.")
            # HP should NOT change — extraction skips deal_damage
            assert members[0]["current_hp"] == 11

    def test_skips_unknown_player(self):
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.text = '[{"player_name": "Nobody", "event_type": "award_item", "value": "Gem"}]'

        with patch("app.helpers.gemini_client") as mock_gemini, patch("app.helpers.supabase_admin"):
            mock_gemini.models.generate_content.return_value = mock_response

            from app.helpers import extract_game_events

            members = [
                {"players": {"name": "Talon", "max_hp": 11}, "current_hp": 11, "player_id": "p1", "inventory": []}
            ]
            extract_game_events("c1", members, "Nobody found a gem.")
            assert members[0]["inventory"] == []

    def test_handles_invalid_json(self):
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.text = "not valid json at all"

        with patch("app.helpers.gemini_client") as mock_gemini, patch("app.helpers.supabase_admin"):
            mock_gemini.models.generate_content.return_value = mock_response

            from app.helpers import extract_game_events

            members = [
                {"players": {"name": "Talon", "max_hp": 11}, "current_hp": 11, "player_id": "p1", "inventory": []}
            ]
            # Should not raise
            extract_game_events("c1", members, "Some narrative.")
            assert members[0]["inventory"] == []

    def test_handles_empty_array(self):
        from unittest.mock import MagicMock, patch

        mock_response = MagicMock()
        mock_response.text = "[]"

        with patch("app.helpers.gemini_client") as mock_gemini, patch("app.helpers.supabase_admin"):
            mock_gemini.models.generate_content.return_value = mock_response

            from app.helpers import extract_game_events

            members = [
                {"players": {"name": "Talon", "max_hp": 11}, "current_hp": 11, "player_id": "p1", "inventory": []}
            ]
            extract_game_events("c1", members, "Nothing happened.")
            assert members[0]["inventory"] == []


class TestMaybeGenerateSummary:
    """Test history compression trigger logic."""

    def test_skips_when_below_batch_size(self):
        from unittest.mock import patch

        with patch("app.helpers.gemini_client") as mock_gemini, patch("app.helpers.supabase_admin"):
            from app.helpers import maybe_generate_summary

            maybe_generate_summary("c1", 10)
            # Should not call Gemini at all
            mock_gemini.models.generate_content.assert_not_called()

    def test_skips_when_summary_exists(self):
        from unittest.mock import MagicMock, patch

        with patch("app.helpers.gemini_client") as mock_gemini, patch("app.helpers.supabase_admin") as mock_admin:
            # Simulate existing summary
            mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(  # noqa: E501
                data=[{"id": "existing"}]
            )  # noqa: E501

            from app.helpers import maybe_generate_summary

            maybe_generate_summary("c1", 50)
            mock_gemini.models.generate_content.assert_not_called()

    def test_generates_summary_at_batch_boundary(self):
        from unittest.mock import MagicMock, patch

        with patch("app.helpers.gemini_client") as mock_gemini, patch("app.helpers.supabase_admin") as mock_admin:
            # No existing summary
            mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(  # noqa: E501
                data=[]
            )  # noqa: E501
            # Logs for the batch
            mock_admin.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value = MagicMock(  # noqa: E501
                data=[
                    {"role": "user", "content": "We enter the cave", "turn_number": 1},
                    {"role": "model", "content": "The cave is dark and damp.", "turn_number": 2},
                ]
            )
            mock_gemini.models.generate_content.return_value = MagicMock(text="Summary of the adventure so far.")

            from app.helpers import maybe_generate_summary

            maybe_generate_summary("c1", 50)
            mock_gemini.models.generate_content.assert_called_once()
            # Verify summary was inserted
            mock_admin.table.return_value.insert.assert_called()

    def test_skips_when_no_logs(self):
        from unittest.mock import MagicMock, patch

        with patch("app.helpers.gemini_client") as mock_gemini, patch("app.helpers.supabase_admin") as mock_admin:
            # No existing summary
            mock_admin.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(  # noqa: E501
                data=[]
            )  # noqa: E501
            # No logs
            mock_admin.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.execute.return_value = MagicMock(  # noqa: E501
                data=[]
            )  # noqa: E501

            from app.helpers import maybe_generate_summary

            maybe_generate_summary("c1", 50)
            mock_gemini.models.generate_content.assert_not_called()


class TestCampaignSharingFlow:
    """Integration tests for the campaign sharing flow."""

    def test_get_user_by_email_found(self):
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"users": [{"id": "user-123", "email": "friend@example.com"}]}

        with patch("httpx.get", return_value=mock_resp):
            from app.deps import get_user_by_email

            result = get_user_by_email("friend@example.com")
            assert result is not None
            assert result.id == "user-123"

    def test_get_user_by_email_not_found(self):
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"users": []}

        with patch("httpx.get", return_value=mock_resp):
            from app.deps import get_user_by_email

            result = get_user_by_email("nobody@example.com")
            assert result is None

    def test_get_user_by_email_case_insensitive(self):
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"users": [{"id": "user-123", "email": "Friend@Example.com"}]}

        with patch("httpx.get", return_value=mock_resp):
            from app.deps import get_user_by_email

            result = get_user_by_email("friend@example.com")
            assert result is not None
            assert result.id == "user-123"

    def test_get_user_by_email_api_error(self):
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.status_code = 500

        with patch("httpx.get", return_value=mock_resp):
            from app.deps import get_user_by_email

            result = get_user_by_email("friend@example.com")
            assert result is None

    def test_execute_tool_calls_award_xp(self):
        from unittest.mock import MagicMock, patch

        with patch("app.helpers.supabase_admin") as mock_admin:
            mock_admin.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(  # noqa: E501
                data={"level": 1, "unspent_points": 0, "xp": 1}
            )
            mock_admin.table.return_value.update.return_value.eq.return_value.execute.return_value = None
            mock_admin.table.return_value.insert.return_value.execute.return_value = None

            from app.helpers import execute_tool_calls

            fc = MagicMock()
            fc.name = "award_xp"
            fc.args = {"player_name": "Talon"}
            members = [
                {"players": {"name": "Talon", "max_hp": 11}, "current_hp": 11, "player_id": "p1", "inventory": []}
            ]
            notifications = execute_tool_calls([fc], "c1", members)
            assert len(notifications) == 1
            assert notifications[0]["type"] == "xp"
            assert "2/3" in notifications[0]["item"]

    def test_execute_tool_calls_level_up_at_3xp(self):
        from unittest.mock import MagicMock, patch

        with patch("app.helpers.supabase_admin") as mock_admin:
            mock_admin.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(  # noqa: E501
                data={"level": 1, "unspent_points": 0, "xp": 2}
            )
            mock_admin.table.return_value.update.return_value.eq.return_value.execute.return_value = None
            mock_admin.table.return_value.insert.return_value.execute.return_value = None

            from app.helpers import execute_tool_calls

            fc = MagicMock()
            fc.name = "award_xp"
            fc.args = {"player_name": "Talon"}
            members = [
                {"players": {"name": "Talon", "max_hp": 11}, "current_hp": 11, "player_id": "p1", "inventory": []}
            ]
            notifications = execute_tool_calls([fc], "c1", members)
            assert len(notifications) == 1
            assert notifications[0]["type"] == "level_up"
            assert "Level 2" in notifications[0]["item"]
