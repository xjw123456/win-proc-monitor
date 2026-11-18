# -*- coding: utf-8 -*-
"""性能分析：统计 + 规则判定。

三条主线：
1) CPU 是否超标；2) 内存占用是否超标；3) 监控期内内存有没有正常释放。
每条结论都给「标准 / 实测 / 判定」，报告直接引用，不写"看起来还行"这种话。
"""

PASS = "pass"
WARN = "warn"
FAIL = "fail"
UNKNOWN = "unknown"

LEVEL_TEXT = {PASS: "通过", WARN: "关注", FAIL: "不通过", UNKNOWN: "样本不足", "info": "参考"}
LEVEL_ORDER = {PASS: 0, UNKNOWN: 1, WARN: 2, FAIL: 3}


# --------------------------------------------------------------------------
# 统计工具
# --------------------------------------------------------------------------
def mean(xs):
    return sum(xs) / float(len(xs)) if xs else 0.0


def median(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def percentile(xs, p):
    """线性插值分位数，p ∈ [0,100]。"""
    if not xs:
        return 0.0
    s = sorted(xs)
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def stdev(xs):
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def linreg(xs, ys):
    """最小二乘，返回 (slope, intercept, r2)。"""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[0] if ys else 0.0), 0.0
    mx = mean(xs)
    my = mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return 0.0, my, 0.0
    slope = sxy / sxx
    intercept = my - slope * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
    r2 = 0.0 if ss_tot == 0 else max(0.0, 1.0 - ss_res / ss_tot)
    return slope, intercept, r2


def _worst(levels):
    best = PASS
    for lv in levels:
        if LEVEL_ORDER.get(lv, 0) > LEVEL_ORDER.get(best, 0):
            best = lv
    return best


# --------------------------------------------------------------------------
# CPU
# --------------------------------------------------------------------------
def analyze_cpu(samples, th, cores):
    rows = [s for s in samples if getattr(s, "cpu_pct", None) is not None]
    result = {
        "count": len(rows),
        "avg": None, "p50": None, "p95": None, "max": None,
        "max_rel_s": None, "max_ts": None,
        "longest_80_s": 0.0, "above_80_total_s": 0.0, "segments": [],
        "verdict": UNKNOWN, "metrics": [], "reasons": [],
    }
    if len(rows) < 2:
        result["reasons"].append("CPU 有效样本不足（<2 个），无法判定")
        return result

    vals = [s.cpu_pct for s in rows]
    avg_v = mean(vals)
    p95_v = percentile(vals, 95)
    max_v = max(vals)
    max_row = max(rows, key=lambda s: s.cpu_pct)

    result.update({
        "avg": avg_v, "p50": median(vals), "p95": p95_v, "max": max_v,
        "max_rel_s": max_row.rel_s, "max_ts": max_row.ts,
    })

    # 持续高占用：连续样本段（按实际间隔累计）
    segs = []
    cur = None
    for s in rows:
        if s.cpu_pct >= th["sustained_threshold"]:
            dur = (s.dt_ms or 0) / 1000.0
            if cur is None:
                cur = {"start_rel": s.rel_s - dur, "start_ts": s.ts,
                       "end_rel": s.rel_s, "end_ts": s.ts, "dur": dur,
                       "peak": s.cpu_pct}
            else:
                cur["end_rel"] = s.rel_s
                cur["end_ts"] = s.ts
                cur["dur"] += dur
                cur["peak"] = max(cur["peak"], s.cpu_pct)
        else:
            if cur:
                segs.append(cur)
                cur = None
    if cur:
        segs.append(cur)

    longest = max([g["dur"] for g in segs]) if segs else 0.0
    total = sum(g["dur"] for g in segs)
    result["segments"] = segs
    result["longest_80_s"] = longest
    result["above_80_total_s"] = total

    lv_avg = FAIL if avg_v > th["avg_fail"] else (WARN if avg_v > th["avg"] else PASS)
    lv_p95 = FAIL if p95_v > th["p95_fail"] else (WARN if p95_v > th["p95"] else PASS)
    lv_max = FAIL if max_v > th["peak_fail"] else (WARN if max_v > th["peak"] else PASS)
    lv_sus = FAIL if longest > th["sustained_fail_s"] else (
        WARN if longest > th["sustained_s"] else PASS)

    result["metrics"] = [
        {"name": "平均 CPU 占用率", "standard": "≤ %.0f%%" % th["avg"],
         "actual": "%.2f%%" % avg_v, "level": lv_avg},
        {"name": "P95 CPU 占用率", "standard": "≤ %.0f%%" % th["p95"],
         "actual": "%.2f%%" % p95_v, "level": lv_p95},
        {"name": "峰值 CPU 占用率", "standard": "≤ %.0f%%（>%.0f%% 直接不通过）" % (th["peak"], th["peak_fail"]),
         "actual": "%.2f%%（%s）" % (max_v, max_row.ts.strftime("%H:%M:%S")), "level": lv_max},
        {"name": "持续高占用（≥%.0f%% %.0fs）" % (th["sustained_threshold"], th["sustained_s"]),
         "standard": "最长 ≤ %.0fs" % th["sustained_s"],
         "actual": "最长 %.0fs（累计 %.0fs）" % (longest, total), "level": lv_sus},
    ]
    result["verdict"] = _worst([lv_avg, lv_p95, lv_max, lv_sus])
    if lv_avg != PASS:
        result["reasons"].append("平均占用率 %.2f%% 超出标准 %.0f%%" % (avg_v, th["avg"]))
    if lv_p95 != PASS:
        result["reasons"].append("P95 占用率 %.2f%% 超出标准 %.0f%%" % (p95_v, th["p95"]))
    if lv_max != PASS:
        result["reasons"].append("峰值 %.2f%% 超出标准 %.0f%%" % (max_v, th["peak"]))
    if lv_sus != PASS:
        result["reasons"].append("持续 ≥%.0f%% 达 %.0fs，超出 %.0fs" % (
            th["sustained_threshold"], longest, th["sustained_s"]))
    return result


# --------------------------------------------------------------------------
# 内存占用
# --------------------------------------------------------------------------
def analyze_mem(samples, th, total_mb):
    rows = [s for s in samples if getattr(s, "priv_mb", None) is not None]
    result = {
        "count": len(rows),
        "baseline_mb": None, "peak_mb": None, "peak_at": None, "peak_pct": None,
        "end_mb": None, "growth_pct": None, "slope": None, "r2": None,
        "verdict": UNKNOWN, "metrics": [], "reasons": [],
    }
    if len(rows) < 3:
        result["reasons"].append("内存有效样本不足（<3 个），无法判定")
        return result

    vals = [s.priv_mb for s in rows]
    base_pool = [s.priv_mb for s in rows if s.rel_s <= 60] or vals[:10]
    baseline = median(base_pool)
    peak = max(vals)
    peak_row = max(rows, key=lambda s: s.priv_mb)
    end = vals[-1]

    slope, _, r2 = linreg([s.rel_s / 60.0 for s in rows], vals)
    growth = ((end - baseline) / baseline * 100.0) if baseline > 0 else 0.0
    peak_pct = (peak / total_mb * 100.0) if total_mb else 0.0

    lv_peak = FAIL if peak_pct > th["peak_percent_fail"] else (
        WARN if peak_pct > th["peak_percent"] else PASS)
    grew_mb = end - baseline
    lv_growth = WARN if (growth > th["growth_percent"] and grew_mb > 50) else PASS

    result.update({
        "baseline_mb": baseline, "peak_mb": peak, "peak_at": peak_row.ts,
        "peak_rel_s": peak_row.rel_s, "peak_pct": peak_pct, "end_mb": end,
        "growth_mb": grew_mb, "growth_pct": growth, "slope": slope, "r2": r2,
    })

    result["metrics"] = [
        {"name": "峰值内存（私有工作集）", "standard": "≤ 物理内存的 %.0f%%" % th["peak_percent"],
         "actual": "%.1f MB / %.1f%%（%s）" % (peak, peak_pct, peak_row.ts.strftime("%H:%M:%S")),
         "level": lv_peak},
        {"name": "基线内存", "standard": "监控前 60s 中位数",
         "actual": "%.1f MB" % baseline, "level": "info"},
        {"name": "期末内存", "standard": "—",
         "actual": "%.1f MB（较基线 %+.1f%%）" % (end, growth), "level": lv_growth},
    ]
    result["verdict"] = _worst([lv_peak, lv_growth])
    if lv_peak != PASS:
        result["reasons"].append("峰值占物理内存 %.1f%%，超出标准 %.0f%%" % (peak_pct, th["peak_percent"]))
    if lv_growth == WARN:
        result["reasons"].append("期末较基线增长 %.1f%%（%+.1f MB）" % (growth, grew_mb))
    return result


# --------------------------------------------------------------------------
# 内存释放趋势
# --------------------------------------------------------------------------
def analyze_release(samples, th, mem_result):
    rows = [s for s in samples if getattr(s, "priv_mb", None) is not None]
    result = {"count": 0, "events": [], "verdict": UNKNOWN, "label": "",
              "metrics": [], "reasons": [], "slope": None, "r2": None}
    if len(rows) < th["min_samples"]:
        result["label"] = "样本不足"
        result["reasons"].append("样本 %d 条（< %d 条），不足以判断释放趋势" % (
            len(rows), th["min_samples"]))
        return result

    vals = [s.priv_mb for s in rows]
    baseline = mem_result.get("baseline_mb") or median(vals[:30])
    drop_thr = max(th["min_drop_mb"], baseline * th["min_drop_percent"] / 100.0)
    band = baseline + max(baseline * th["recover_band_percent"] / 100.0, 80.0)

    # 窗口（按 2s 采样换算成样本数，最小 1）
    step = max(1.0, th["sample_interval"])
    half_win = max(2, int(45.0 / step))
    fwd_win = max(3, int(th["window_s"] / step))

    events = []
    i = 0
    n = len(rows)
    while i < n:
        lo = max(0, i - half_win)
        hi = min(n, i + half_win + 1)
        window = vals[lo:hi]
        # 局部峰值：自身是窗口最大值，且相对窗口最小值有足够涨幅
        if vals[i] >= max(window) and (vals[i] - min(window)) >= drop_thr:
            # 向后找回落谷值
            fwd_hi = min(n, i + fwd_win + 1)
            j_best = None
            v_best = vals[i]
            for j in range(i + 1, fwd_hi):
                if vals[j] < v_best:
                    v_best = vals[j]
                    j_best = j
            if j_best is not None and (vals[i] - v_best) >= drop_thr and v_best <= band:
                events.append({
                    "peak_mb": vals[i], "peak_ts": rows[i].ts,
                    "peak_rel_s": rows[i].rel_s,
                    "trough_mb": v_best, "trough_ts": rows[j_best].ts,
                    "trough_rel_s": rows[j_best].rel_s,
                    "drop_mb": vals[i] - v_best,
                    "drop_pct": (vals[i] - v_best) / vals[i] * 100.0 if vals[i] else 0.0,
                    "duration_s": rows[j_best].rel_s - rows[i].rel_s,
                })
                i = j_best + 1
                continue
        i += 1

    slope = mem_result.get("slope")
    r2 = mem_result.get("r2")
    if slope is None:
        slope, _, r2 = linreg([s.rel_s / 60.0 for s in rows], vals)

    count = len(events)
    end = vals[-1]
    result.update({"count": count, "events": events, "slope": slope, "r2": r2})

    lv = PASS
    if count >= 1 and end <= baseline * 1.2 and slope <= th["slope_mb_per_min"]:
        label = "正常释放"
        reason = "出现 %d 次有效释放，期末 %.1f MB 回到基线带内，斜率 %.2f MB/min" % (
            count, end, slope)
    elif count == 0 and slope > th["leak_slope_mb_per_min"] and r2 >= 0.7:
        lv = FAIL
        label = "疑似内存泄漏"
        reason = "全程无有效释放，线性增长斜率 %.2f MB/min（R²=%.2f）" % (slope, r2)
    elif count == 0 and slope > th["slope_mb_per_min"]:
        lv = WARN
        label = "持续增长、未见释放"
        reason = "无有效释放，斜率 %.2f MB/min 高于 %.1f MB/min" % (slope, th["slope_mb_per_min"])
    elif count >= 1 and end > baseline * 1.2:
        lv = WARN
        label = "有释放但整体上移"
        reason = "有 %d 次释放，但期末 %.1f MB 仍高于基线的 1.2 倍（%.1f MB）" % (
            count, end, baseline * 1.2)
    elif baseline and (stdev(vals) / baseline * 100.0) < 5.0:
        label = "内存稳定"
        reason = "全程波动小于 5%，无明显释放压力"
    elif count >= 1:
        label = "有释放、整体平稳"
        reason = "出现 %d 次有效释放，期末 %.1f MB，斜率 %.2f MB/min" % (count, end, slope)
    else:
        label = "无明显释放，内存平稳"
        reason = "未见有效释放，斜率 %.2f MB/min 未达告警线" % slope

    result["label"] = label
    result["verdict"] = lv
    result["reasons"].append(reason)
    result["metrics"] = [
        {"name": "有效释放次数", "standard": "≥1 次视为有释放行为",
         "actual": "%d 次" % count, "level": lv},
        {"name": "回落判定阈值", "standard": "跌幅 ≥ max(%.0f MB, 基线%.0f%%)" % (
            th["min_drop_mb"], th["min_drop_percent"]),
         "actual": "本次 %.1f MB" % drop_thr, "level": PASS},
        {"name": "内存增长斜率", "standard": "≤ %.1f MB/min" % th["slope_mb_per_min"],
         "actual": "%.2f MB/min（R²=%.2f）" % (slope, r2), "level": lv},
    ]
    return result


# --------------------------------------------------------------------------
# 汇总
# --------------------------------------------------------------------------
def analyze(samples, meta, th):
    cores = max(1, int(meta.get("cores") or 1))
    total_mb = float(meta.get("total_phys_mb") or 0.0)

    cpu = analyze_cpu(samples, th["cpu"], cores)
    mem = analyze_mem(samples, th["mem"], total_mb)
    rel = analyze_release(samples, th["release"], mem)

    overall = _worst([cpu["verdict"], mem["verdict"], rel["verdict"]])

    warnings = []
    if meta.get("exited"):
        warnings.append("目标进程在监控期间退出，数据截至 %s" % meta.get("exited_at_text", ""))
    if meta.get("paused_count"):
        warnings.append("监控期间暂停 %d 次" % meta["paused_count"])
    if len(samples) < th["release"]["min_samples"]:
        warnings.append("样本偏少（%d 条），建议监控 ≥ 5 分钟以获得可靠趋势判断" % len(samples))

    return {
        "overall": overall,
        "overall_text": LEVEL_TEXT.get(overall, "—"),
        "cpu": cpu,
        "mem": mem,
        "release": rel,
        "warnings": warnings,
        "sample_count": len(samples),
        "duration_s": meta.get("duration_s") or (samples[-1].rel_s if samples else 0.0),
    }


DEFAULT_THRESHOLDS = {
    "cpu": {
        "avg": 50.0, "avg_fail": 70.0,
        "p95": 70.0, "p95_fail": 85.0,
        "peak": 90.0, "peak_fail": 95.0,
        "sustained_threshold": 80.0, "sustained_s": 30.0, "sustained_fail_s": 120.0,
    },
    "mem": {
        "peak_percent": 80.0, "peak_percent_fail": 90.0, "growth_percent": 20.0,
    },
    "release": {
        "min_drop_mb": 50.0, "min_drop_percent": 5.0, "recover_band_percent": 15.0,
        "window_s": 120.0, "slope_mb_per_min": 3.0, "leak_slope_mb_per_min": 5.0,
        "min_samples": 30, "sample_interval": 2.0,
    },
}


def merge_thresholds(user):
    """把用户配置合并进默认阈值，缺字段就补默认。"""
    out = {}
    user = user if isinstance(user, dict) else {}
    for section, defaults in DEFAULT_THRESHOLDS.items():
        merged = dict(defaults)
        for k, v in (user.get(section) or {}).items():
            try:
                merged[k] = float(v)
            except (TypeError, ValueError):
                pass
        out[section] = merged
    return out