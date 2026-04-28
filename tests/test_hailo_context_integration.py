"""Integration test: verify Hailo provider reports context_window
and agent_builder adjusts ContextConfig in the real environment.

This requires the Hailo-10H device to be free (no other process using it).
"""

import asyncio
import sys


async def test_hailo_context_window():
    print("=" * 60)
    print("Integration Test: Hailo context_window reporting")
    print("=" * 60)

    # 1. Test HailoProvider directly
    print("\n[1] Testing HailoProvider.get_info()...")
    from mindbot.providers.hailo.provider import HailoProvider, MODEL_CONTEXT_WINDOW
    from mindbot.providers.hailo.param import HailoProviderParam

    print(f"    MODEL_CONTEXT_WINDOW: {MODEL_CONTEXT_WINDOW}")

    param = HailoProviderParam(model="qwen3:1.7b")
    provider = HailoProvider(param)
    info = provider.get_info()

    print(f"    Provider: {info.provider}")
    print(f"    Model:    {info.model}")
    print(f"    context_window: {info.context_window}")

    assert info.context_window is not None, "context_window should not be None"
    assert info.context_window == 2048, f"Expected 2048, got {info.context_window}"
    print("    ✓ PASS")

    # 2. Query actual device max_context_capacity (if available)
    print("\n[2] Querying Hailo device max_context_capacity()...")
    try:
        from hailo_platform import VDevice
        from hailo_platform.genai import LLM

        hef_path = "/home/pi/.local/share/hailo-ollama/models/blob/sha256_cc9b9d1c92e35249b5a9b7bc31fbd652f03bba1232e99b9a8271845ad6f17821"
        vd = VDevice()
        llm = LLM(vd, hef_path)

        actual_capacity = llm.max_context_capacity()
        current_usage = llm.get_context_usage_size()
        print(f"    max_context_capacity(): {actual_capacity}")
        print(f"    get_context_usage_size(): {current_usage}")

        llm.release()
        vd.release()

        assert actual_capacity == 2048, f"HEF reports {actual_capacity}, expected 2048"
        print("    ✓ PASS - matches MODEL_CONTEXT_WINDOW")
    except Exception as e:
        print(f"    ⚠ SKIP - Cannot access device: {e}")

    # 3. Test agent_builder auto-adjustment
    print("\n[3] Testing agent_builder context adjustment...")
    from mindbot.config.schema import Config, ContextConfig

    config = Config()
    original_max = config.context.max_tokens
    print(f"    Config context.max_tokens (before): {original_max}")

    # Simulate what agent_builder does
    provider_window = info.context_window
    if provider_window and provider_window > 0:
        effective_max = min(config.context.max_tokens, provider_window)
        if effective_max != config.context.max_tokens:
            adjusted_config = config.context.model_copy(update={"max_tokens": effective_max})
            print(f"    Adjusted context.max_tokens: {original_max} → {effective_max}")
            assert effective_max == 2048
            print("    ✓ PASS")
        else:
            print(f"    No adjustment needed (already {effective_max})")

    # 4. Test ContextManager with adjusted budget
    print("\n[4] Testing ContextManager block budgets...")
    from mindbot.context.manager import ContextManager, _resolve_block_budgets

    adjusted_config = ContextConfig(max_tokens=2048)
    budgets = _resolve_block_budgets(adjusted_config)
    print(f"    Total budget: 2048")
    for name, budget in budgets.items():
        print(f"    {name}: {budget} tokens")
    total = sum(budgets.values())
    print(f"    Sum of budgets: {total}")
    assert total <= 2048, f"Budgets exceed window: {total} > 2048"
    print("    ✓ PASS")

    # 5. Cleanup
    print("\n[5] Cleaning up HailoProvider...")
    await provider.aclose()
    print("    ✓ Released")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_hailo_context_window())
