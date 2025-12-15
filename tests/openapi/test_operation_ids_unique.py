from arche_api.main import app


def test_operation_ids_are_unique() -> None:
    spec = app.openapi()
    ops: list[str] = []
    for _path, methods in spec.get("paths", {}).items():
        for _method, data in methods.items():
            oid = data.get("operationId")
            if oid:
                ops.append(oid)
    assert len(ops) == len(set(ops)), "Duplicate OpenAPI operationIds detected"
