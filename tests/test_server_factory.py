import unittest

from common.server_factory import SERVICE_CONFIGS, create_mcp


class ServerFactoryTests(unittest.TestCase):
    def test_enterprise_service_uses_its_name_port_and_route(self):
        config = SERVICE_CONFIGS["enterprise"]

        self.assertEqual(config.name, "enterprise-mcp")
        self.assertEqual(config.port, 8908)
        self.assertEqual(config.streamable_http_path, "/cece-mcp-servers/enterprise/stream")

    def test_create_mcp_uses_selected_service_configuration(self):
        mcp = create_mcp("enterprise")

        self.assertEqual(mcp.name, "enterprise-mcp")
        self.assertIn("search_enterprise_by_name", mcp.instructions)
        self.assertIn("最多重试一次", mcp.instructions)

    def test_custom_instructions_take_effect(self):
        mcp = create_mcp("finance")

        self.assertEqual(mcp.name, "finance-mcp")
        self.assertIn("创投融资服务", mcp.instructions)
