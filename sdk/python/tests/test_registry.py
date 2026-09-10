import os
import tempfile

import pytest

from gluless.models import SideEffectType, Utility, UtilityTransport, UtilityType
from gluless.registry import UtilityRegistry


@pytest.fixture
def temp_registry_file():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)

def test_registry_registration_and_preservation(temp_registry_file):
    registry = UtilityRegistry(registry_path=temp_registry_file)

    # Define a mock utility
    transport = UtilityTransport(
        type="openapi",
        method="POST",
        path="/sessions/{id}/nudge",
        parameters=[{"name": "id", "in": "path", "required": True}],
        request_body={"properties": {"force": {"type": "boolean"}}},
        responses={"200": {"type": "object"}}
    )
    utility = Utility(
        id="GasCity.sessions.nudge",
        name="sessions.nudge",
        namespace="GasCity",
        description="Nudge a session",
        type=UtilityType.MUTATION,
        side_effects=SideEffectType.UPDATE,
        transport=transport,
        auth=[{"type": "oauth2"}]
    )

    # Register utility
    registry_id = registry.register(
        utility=utility,
        source_uri="file:///mock/openapi.yaml",
        source_digest="sha256-mockdigest123"
    )

    assert registry_id == "utility://gascity/sessions.nudge"

    # Reload registry from disk
    new_registry = UtilityRegistry(registry_path=temp_registry_file)
    assert registry_id in new_registry.utilities

    ut_data = new_registry.utilities[registry_id]
    assert ut_data["source_uri"] == "file:///mock/openapi.yaml"
    assert ut_data["side_effect"]["declared"] == "update"
    assert ut_data["side_effect"]["observed"] == "unknown"  # Observed default
    assert ut_data["side_effect"]["confidence"] == 0.0

    # Test update_observation
    new_registry.update_observation(registry_id, "process_restart", 0.95)

    refreshed_registry = UtilityRegistry(registry_path=temp_registry_file)
    assert refreshed_registry.utilities[registry_id]["side_effect"]["observed"] == "process_restart"
    assert refreshed_registry.utilities[registry_id]["side_effect"]["confidence"] == 0.95
    assert refreshed_registry.utilities[registry_id]["side_effect"]["samples"] == 1

def test_registry_search_and_resolve(temp_registry_file):
    registry = UtilityRegistry(registry_path=temp_registry_file)

    # Register a read utility
    read_transport = UtilityTransport(type="openapi", method="GET", path="/cities")
    read_utility = Utility(
        id="GasCity.cities.list",
        name="cities.list",
        namespace="GasCity",
        description="List all cities",
        type=UtilityType.READ,
        side_effects=SideEffectType.READ,
        transport=read_transport
    )
    registry.register(read_utility, "file:///mock/openapi.yaml", "digest1")

    # Register a mutation utility
    mut_transport = UtilityTransport(
        type="openapi",
        method="POST",
        path="/destroy",
        parameters=[{"name": "id", "in": "query"}]
    )
    mut_utility = Utility(
        id="GasCity.cities.destroy",
        name="cities.destroy",
        namespace="GasCity",
        description="Destroy city",
        type=UtilityType.MUTATION,
        side_effects=SideEffectType.INFRASTRUCTURE,
        transport=mut_transport
    )
    registry.register(mut_utility, "file:///mock/openapi.yaml", "digest1")

    # 1. Search for read utilities in gascity domain
    read_results = registry.search({"domain": "gascity", "max_effect": "read"})
    assert len(read_results) == 1
    assert read_results[0]["operation_id"] == "GasCity.cities.list"

    # 2. Search for utilities requiring specific input parameter
    input_results = registry.search({"requires_input": "id"})
    assert len(input_results) == 1
    assert input_results[0]["operation_id"] == "GasCity.cities.destroy"

    # 3. Resolve registered ID back to Utility object
    resolved = registry.resolve("utility://gascity/cities.list")
    assert resolved is not None
    assert resolved.id == "GasCity.cities.list"
    assert resolved.type == UtilityType.READ
    assert resolved.side_effects == SideEffectType.READ
