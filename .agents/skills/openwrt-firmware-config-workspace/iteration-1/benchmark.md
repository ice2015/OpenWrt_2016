# Skill Benchmark: openwrt-firmware-config

**Model**: Codex session model (identifier not exposed)
**Date**: 2026-11-13T07:53:59Z
**Evals**: 1, 2, 3 (1 run each per configuration)

## Summary

| Metric | With Skill | Without Skill | Delta |
|--------|------------|---------------|-------|
| Pass Rate | 100% ± 0% | 67% ± 58% | +0.33 |
| Time | 0.0s ± 0.0s | 0.0s ± 0.0s | +0.0s |
| Tokens | 0 ± 0 | 0 ± 0 | +0 |

## Notes

- Raspberry Pi 与 OpenClash 场景在两组中都通过，主要用于防回归，不用于证明 Skill 提升。
- m4/ccache 场景具有区分度：无 Skill 为 0/3，有 Skill 为 3/3；诊断顺序从先删缓存变为先核对 `CONFIG_CCACHE_DIR`、`build.config` 和 `config.log`。
- 运行时未提供 token 与耗时字段，因此表中的 0 表示不可用，不能用于性能比较。
