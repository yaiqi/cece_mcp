import unittest

from entity_mcp.common.server_factory import SERVICE_CONFIGS, create_mcp


class ServerFactoryTests(unittest.TestCase):
    def test_group_service_uses_its_name_port_and_route(self):
        config = SERVICE_CONFIGS["group"]

        self.assertEqual(config.name, "group-mcp")
        self.assertEqual(config.port, 8902)
        self.assertEqual(config.streamable_http_path, "/mcp/group/stream")

    def test_create_mcp_uses_selected_service_configuration(self):
        mcp = create_mcp("group")

        self.assertEqual(mcp.name, "group-mcp")
        self.assertIn("resolve_group", mcp.instructions)
        self.assertIn("最多重试一次", mcp.instructions)
