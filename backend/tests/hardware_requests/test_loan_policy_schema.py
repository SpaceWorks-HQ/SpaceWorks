from drf_spectacular.generators import SchemaGenerator


def test_loan_policy_and_renewal_routes_document_inputs_and_errors():
    schema = SchemaGenerator().get_schema(request=None, public=True)
    paths = schema["paths"]
    policy = paths["/api/v1/admin/makerspace/{makerspace_id}/return-policy"]
    for method in ("get", "patch"):
        assert {"200", "400", "401", "403", "404"} <= set(policy[method]["responses"])
    assert "requestBody" in policy["patch"]
    for prefix in ("/api/v1/member/makerspaces/", "/api/v1/admin/makerspace/"):
        renewals = [operations for path, operations in paths.items()
                    if path.startswith(prefix) and "/loans/" in path and path.endswith("/renew")]
        assert len(renewals) == 1
        operation = renewals[0]["post"]
        assert "requestBody" in operation
        assert {"200", "400", "401", "403", "404"} <= set(operation["responses"])
