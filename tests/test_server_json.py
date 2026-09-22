"""
Tests: server.json MCP Registry manifest

Validates the server.json file exists and conforms to the MCP Registry schema.
"""

import json
import os
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_JSON_PATH = os.path.join(REPO_ROOT, "server.json")


class TestServerJson:
    @pytest.fixture(autouse=True)
    def load_manifest(self):
        with open(SERVER_JSON_PATH, "r") as f:
            self.manifest = json.load(f)

    def test_file_exists(self):
        assert os.path.isfile(SERVER_JSON_PATH)

    def test_has_schema_field(self):
        assert "$schema" in self.manifest
        assert "modelcontextprotocol.io" in self.manifest["$schema"]

    def test_has_name(self):
        assert "name" in self.manifest
        assert "slaughters85j" in self.manifest["name"]

    def test_has_description(self):
        assert "description" in self.manifest
        assert len(self.manifest["description"]) > 20

    def test_has_repository(self):
        repo = self.manifest.get("repository", {})
        assert "url" in repo
        assert "github.com/slaughters85j" in repo["url"]
        assert repo.get("source") == "github"

    def test_has_packages(self):
        pkgs = self.manifest.get("packages", [])
        assert len(pkgs) >= 1
        pkg = pkgs[0]
        assert pkg.get("registryType") == "pypi"
        assert "identifier" in pkg
        assert pkg.get("transport", {}).get("type") == "stdio"

    def test_valid_json_roundtrip(self):
        """Ensure file is valid JSON that roundtrips cleanly."""
        with open(SERVER_JSON_PATH, "r") as f:
            raw = f.read()
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)
