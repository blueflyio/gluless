from gluless.importers.openapi import OpenAPIImporter, derive_utility_name
from gluless.models import SideEffectType, UtilityType

# Mock OpenAPI specification
MOCK_OPENAPI_SPEC = """
openapi: 3.0.0
info:
  title: GasCity API
  version: 0.1.0
x-provider-name: GasCity
paths:
  /v0/cities:
    get:
      summary: List all healthy cities
      operationId: listCities
      responses:
        '200':
          description: A list of cities
          content:
            application/json:
              schema:
                type: array
                items:
                  $ref: '#/components/schemas/City'
  /v0/sessions/{id}/nudge:
    post:
      summary: Nudge a session
      operationId: nudgeSession
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                force:
                  type: boolean
      responses:
        '200':
          description: Successful nudge
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
  /v0/users/{id}:
    get:
      summary: Get user details
      operationId: getUser
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: string
      responses:
        '200':
          description: User object
          content:
            application/json:
              schema:
                type: object
                properties:
                  name:
                    type: string
  /v0/custom-endpoint:
    post:
      summary: Custom endpoint overriding everything
      operationId: customOp
      x-gluless-name: CustomNS.custom_resource.custom_action
      x-gluless-type: mutation
      x-gluless-side-effects: privilege_change
      responses:
        '200':
          description: Success
components:
  schemas:
    City:
      type: object
      properties:
        name:
          type: string
        health:
          type: string
"""

def test_derive_utility_name():
    # Test listCities (GET /v0/cities)
    assert derive_utility_name("GET", "/v0/cities", "listCities") == ("cities", "list")

    # Test nudgeSession (POST /v0/sessions/{id}/nudge)
    assert derive_utility_name("POST", "/v0/sessions/{id}/nudge", "nudgeSession") == ("sessions", "nudge")

    # Test getUser (GET /v0/users/{id})
    assert derive_utility_name("GET", "/v0/users/{id}", "getUser") == ("users", "read")

    # Test custom POST without operationId
    assert derive_utility_name("POST", "/v0/tasks") == ("tasks", "create")

    # Test custom DELETE
    assert derive_utility_name("DELETE", "/v0/tasks/{id}") == ("tasks", "delete")


def test_openapi_importer():
    importer = OpenAPIImporter()
    utilities = importer.import_spec(MOCK_OPENAPI_SPEC)

    # We should have 4 utilities parsed
    assert len(utilities) == 4

    # Build a lookup map of utilities by ID
    util_map = {u.id: u for u in utilities}

    # 1. Check listCities (GET /v0/cities)
    assert "GasCity.cities.list" in util_map
    util_cities = util_map["GasCity.cities.list"]
    assert util_cities.namespace == "GasCity"
    assert util_cities.name == "cities.list"
    assert util_cities.type == UtilityType.READ
    assert util_cities.side_effects == SideEffectType.READ
    assert util_cities.description == "List all healthy cities"

    # Check that $ref to City schema was correctly resolved
    response_200 = util_cities.transport.responses["200"]
    assert response_200["type"] == "array"
    assert response_200["items"]["type"] == "object"
    assert "name" in response_200["items"]["properties"]
    assert "health" in response_200["items"]["properties"]

    # 2. Check nudgeSession (POST /v0/sessions/{id}/nudge)
    assert "GasCity.sessions.nudge" in util_map
    util_nudge = util_map["GasCity.sessions.nudge"]
    assert util_nudge.type == UtilityType.MUTATION
    assert util_nudge.side_effects == SideEffectType.UNKNOWN  # RPC-style POST never inherits CREATE authority
    assert len(util_nudge.transport.parameters) == 1
    assert util_nudge.transport.parameters[0]["name"] == "id"
    assert util_nudge.transport.request_body["type"] == "object"
    assert "force" in util_nudge.transport.request_body["properties"]

    # 3. Check getUser (GET /v0/users/{id})
    assert "GasCity.users.read" in util_map
    util_user = util_map["GasCity.users.read"]
    assert util_user.type == UtilityType.READ
    assert util_user.side_effects == SideEffectType.READ

    # 4. Check custom override (POST /v0/custom-endpoint)
    assert "CustomNS.custom_resource.custom_action" in util_map
    util_custom = util_map["CustomNS.custom_resource.custom_action"]
    assert util_custom.namespace == "CustomNS"
    assert util_custom.name == "custom_resource.custom_action"
    assert util_custom.type == UtilityType.MUTATION
    assert util_custom.side_effects == SideEffectType.PRIVILEGE_CHANGE
