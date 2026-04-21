# Vulture whitelist — silences false positives that vulture can't reason about.
#
# All entries here are parameter names on `typing.Protocol` method stubs whose
# body is `...`. Vulture flags them as "unused variable" because the body never
# reads them, but they document the interface that concrete implementations
# must implement. Removing them would change the protocol signature and break
# the type contract.
#
# This file is fed to vulture as an extra input; any name referenced here is
# treated as used. Regenerate with `vulture src/stronghold/ --make-whitelist`
# if new Protocol stubs are added and rescoped to keep only the FPs.

# protocols/agent_pod.py — AgentPodProvider method stubs
agent_type  # AgentPodProvider.ensure_capacity / create_pod / destroy_pod
pod_name  # AgentPodProvider.create_pod / destroy_pod
generation  # AgentPodProvider.create_pod

# protocols/data.py — DataProvider
table  # DataProvider.query stub

# protocols/mcp.py — MCPProvider
deployment_name  # MCPProvider stub

# protocols/memory.py — MemoryStore
team  # MemoryStore.load scope stub

# protocols/secrets.py — SecretsProvider
ref  # SecretsProvider.get / delete stubs

# protocols/tracing.py, tracing/noop.py, tracing/phoenix_backend.py
exc_tb  # TracingBackend.__exit__ stub (standard context-manager signature)
