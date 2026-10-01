import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_template(name: str) -> dict:
    return json.loads((ROOT / "templates" / name).read_text())


def test_api_and_worker_templates_share_import_volume_contract():
    api = load_template("upstream-api-template.json")["template"]
    worker = load_template("upstream-worker-template.json")["template"]
    path = "/var/lib/upstream-bulk-imports"

    assert api["volume_mounts"][path] == worker["volume_mounts"][path]
    assert api["environment_variables"]["BULK_IMPORT_STORAGE_PATH"] == path
    assert worker["environment_variables"]["BULK_IMPORT_STORAGE_PATH"] == path
    assert api["environment_variables"]["BULK_INGESTION_ENABLED"] == "false"
    assert api["environment_variables"]["ASYNC_BULK_INGESTION_ENABLED"] == "false"
    assert worker["environment_variables"]["BULK_INGESTION_ENABLED"] == "false"
    assert worker["environment_variables"]["ASYNC_BULK_INGESTION_ENABLED"] == "false"


def test_worker_template_is_private_and_polling():
    worker = load_template("upstream-worker-template.json")["template"]

    assert "--poll" in worker["command"][-1]
    assert worker["networking"] == {}
    assert worker["image"] == "{{WORKER_IMAGE}}"
    assert not {"TAS_USER", "TAS_SECRET", "JWT_SECRET", "CKAN_ADMIN_API_KEY"}.intersection(
        worker["environment_variables"]
    )


def test_develop_provisioner_requires_explicit_control_plane_and_worker():
    script = (ROOT / "scripts" / "create_develop_pods.py").read_text()

    assert "TAPIS_BASE_URL must be set explicitly" in script
    assert 'IMPORT_VOLUME_ID = "upstreamdevelopimportvolume"' in script
    assert 'WORKER_ID     = "upstreamdevelopworker"' in script
    assert "--poll" in script


def test_workflow_uses_one_digest_for_api_and_worker():
    workflow = (ROOT / ".github" / "workflows" / "build-docker-image.yaml").read_text()

    assert "image-digest:" in workflow
    assert 'DIGEST="${{ needs.build-and-push.outputs.image-digest }}"' in workflow
    assert 'IMAGE="ghcr.io/${{ env.IMAGE_NAME }}@${DIGEST}"' in workflow
    assert 'request_json PUT "/v3/pods/${TAPIS_POD_ID}"' in workflow
    assert 'request_json PUT "/v3/pods/${TAPIS_WORKER_ID}"' in workflow
    assert '"BULK_INGESTION_ENABLED": "false"' in workflow
    assert '"ASYNC_BULK_INGESTION_ENABLED": "false"' in workflow
    assert 'https://portals.tapis.io' in workflow


def test_workflow_provisions_missing_worker_and_shared_volume():
    workflow = (ROOT / ".github" / "workflows" / "build-docker-image.yaml").read_text()

    assert 'IMPORT_VOLUME_ID="upstreamdevelopimportvolume"' in workflow
    assert 'request_json POST "/v3/pods/volumes"' in workflow
    assert 'request_json POST "/v3/pods"' in workflow
    assert 'source_id: $volume' in workflow
    assert 'Existing API pod does not expose DATABASE_URL' in workflow
