"""Lane E section 11 row 8: keep the production W8 caller immutable."""

import json
from types import SimpleNamespace

from apps.backup import compound_slice_build


class _ObjectPlan:
    def closure(self, _component):
        return {"private": {}, "public_image": {}}

    def bind_component(self, *_args):
        return None


def test_compound_slice_passes_the_exact_tuple_enumeration_to_w8(
    monkeypatch, tmp_path
):
    frozen_enumeration = (object(), object())
    observed = []
    item = SimpleNamespace(
        makerspace_id=41,
        slice_id="e10-w8-slice",
        public_recipients=("age1tenant-one", "age1tenant-two"),
        recipient_fingerprints=("1" * 64, "2" * 64),
        custody_state="healthy",
    )

    def tenant_payload(_makerspace_id, rows_root):
        rows_root.mkdir(parents=True)
        (rows_root / "global_user_references.json").write_text(
            "[]", encoding="utf-8"
        )

    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def seal(staged_rows, _recipients, _root):
        observed.append(staged_rows)
        assert type(staged_rows) is tuple
        assert staged_rows is frozen_enumeration
        return ()

    monkeypatch.setattr(
        compound_slice_build, "enumerate_staged_deks", lambda _space: frozen_enumeration
    )
    monkeypatch.setattr(compound_slice_build, "seal_staged_deks", seal)
    monkeypatch.setattr(compound_slice_build, "boundary_deltas", lambda _space: [])
    monkeypatch.setattr(
        compound_slice_build, "verify_unsealed_slice", lambda *_args, **_kwargs: None
    )

    result = compound_slice_build.build_unsealed_slice(
        item,
        work_root=tmp_path,
        tenant_payload=tenant_payload,
        capture_objects=lambda *_args, **_kwargs: [],
        write_json=write_json,
        object_plan=_ObjectPlan(),
        modes={},
        archive_format="e10",
    )

    assert observed == [frozen_enumeration]
    assert result.staged_deks is frozen_enumeration
