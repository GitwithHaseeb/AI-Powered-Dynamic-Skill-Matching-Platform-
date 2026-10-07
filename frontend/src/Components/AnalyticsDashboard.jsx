// src/components/AnalyticsDashboard.jsx
import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { analyticsService, userService, getApiErrorMessage } from '../services/api.js';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Title,
  Tooltip,
  Legend,
  ArcElement,
} from 'chart.js';
import { Bar, Line, Doughnut } from 'react-chartjs-2';

ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Title,
  Tooltip,
  Legend,
  ArcElement
);

const CHART_COLORS = [
  '#3B82F6',
  '#10B981',
  '#F59E0B',
  '#8B5CF6',
  '#EC4899',
  '#6366F1',
  '#14B8A6',
  '#F97316',
  '#84CC16',
  '#A855F7',
  '#06B6D4',
  '#E11D48',
];

const REFRESH_MS = 30000;

const GENERIC_TITLE_WORDS = new Set(['developer', 'dev', 'engineer', 'intern', 'trainee', 'pm', 'manager', 'lead']);

function dedupePeopleCount(rows) {
  if (!Array.isArray(rows)) return 0;
  const seen = new Set();
  for (const r of rows) {
    const rawEmail = String(r?.email ?? r?.contact ?? '').trim().toLowerCase();
    if (rawEmail && rawEmail.includes('@') && rawEmail !== 'not on file') {
      seen.add(`e:${rawEmail}`);
      continue;
    }
    const nmRaw = String(r?.full_name ?? r?.name ?? r?.username ?? '').trim().toLowerCase();
    const clean = nmRaw.replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();
    if (clean) {
      const parts = clean.split(' ');
      let key = clean;
      if (parts.length >= 2 && GENERIC_TITLE_WORDS.has(parts[parts.length - 1])) key = parts[0];
      else if (parts.length === 1) key = parts[0];
      else key = `${parts[0]}_${parts[parts.length - 1]}`;
      seen.add(`n:${key}`);
      continue;
    }
    const sid = String(r?._id ?? r?.id ?? '').trim();
    if (sid) seen.add(`id:${sid}`);
  }
  return seen.size;
}

function buildSkillGapLineFromDetail(g) {
  const detail = Array.isArray(g?.developers_detail) ? g.developers_detail : [];
  const parts = detail
    .map((d) => {
      const nm = d?.name != null ? String(d.name).trim() : '';
      if (!nm || nm.toLowerCase() === 'none' || nm.toLowerCase() === 'unnamed') return null;
      const p = d?.proficiency;
      const pv =
        typeof p === 'number' && Number.isFinite(p) && p > 0
          ? ` (${Number(p).toFixed(1).replace(/\.0$/, '')})`
          : '';
      return `${nm}${pv}`;
    })
    .filter(Boolean);
  if (!parts.length) return '';
  const nn = Math.max(Number(g?.developers_with_skill) || 0, parts.length);
  return `${nn}: ${parts.join(', ')}`;
}

function extractSkillEntriesFromUserRow(u) {
  const out = [];
  const chunks = [u?.skills, u?.Skills, u?.technical_skills, u?.expertise, u?.tech_stack];
  for (const c of chunks) {
    if (!Array.isArray(c)) continue;
    for (const it of c) {
      if (it == null) continue;
      if (typeof it === 'string') {
        const s = it.trim();
        if (s) out.push({ name: s, level: null });
        continue;
      }
      if (typeof it === 'object') {
        const nm = String(
          it.skill_name ?? it.name ?? it.skill ?? it.title ?? it.label ?? ''
        ).trim();
        if (!nm) continue;
        const lvRaw = it.proficiency_level ?? it.proficiency ?? it.level ?? it.score ?? null;
        const lv = Number(lvRaw);
        out.push({ name: nm, level: Number.isFinite(lv) ? lv : null });
      }
    }
  }
  return out;
}

function skillGapLineFromDeveloperProfiles(skillLabel, developersRows) {
  const sk = String(skillLabel ?? '').trim().toLowerCase();
  if (!sk || !Array.isArray(developersRows) || !developersRows.length) return '';
  const byName = new Map();
  for (const u of developersRows) {
    const disp = String(u?.full_name ?? u?.name ?? u?.username ?? '').trim();
    if (!disp) continue;
    const entries = extractSkillEntriesFromUserRow(u);
    let bestLevel = null;
    let hit = false;
    for (const e of entries) {
      const en = String(e?.name ?? '').trim().toLowerCase();
      if (!en) continue;
      if (en === sk || (sk.length >= 3 && en.includes(sk)) || (en.length >= 3 && sk.includes(en))) {
        hit = true;
        if (typeof e.level === 'number' && Number.isFinite(e.level) && e.level > 0) {
          if (bestLevel == null || e.level > bestLevel) bestLevel = e.level;
        }
      }
    }
    if (!hit) continue;
    const prev = byName.get(disp);
    if (prev == null) {
      byName.set(disp, bestLevel);
    } else if (
      typeof bestLevel === 'number' &&
      Number.isFinite(bestLevel) &&
      (prev == null || bestLevel > prev)
    ) {
      byName.set(disp, bestLevel);
    }
  }
  const uniq = [...byName.entries()].map(([nm, lv]) => {
    const lvTxt =
      typeof lv === 'number' && Number.isFinite(lv) && lv > 0
        ? ` (${String(Number(lv).toFixed(1)).replace(/\.0$/, '')})`
        : '';
    return `${nm}${lvTxt}`;
  });
  if (!uniq.length) return '';
  return `${uniq.length}: ${uniq.join(', ')}`;
}

function downloadBlob(content, filename, mime) {
  const blob =
    content instanceof Blob
      ? content
      : new Blob([content], { type: mime || 'application/octet-stream' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

async function alertBlobError(err, fallback) {
  const d = err?.response?.data;
  if (d instanceof Blob) {
    try {
      const t = await d.text();
      const j = JSON.parse(t);
      if (typeof j.detail === 'string' && j.detail.trim()) {
        alert(j.detail);
        return;
      }
    } catch {
      /* ignore */
    }
  }
  alert(getApiErrorMessage(err, fallback));
}

const AnalyticsDashboard = () => {
  const [timeFrame, setTimeFrame] = useState('month');
  const [liveSummary, setLiveSummary] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [actionLoading, setActionLoading] = useState(null);
  const [usingAllFallback, setUsingAllFallback] = useState(false);
  const [usingChartAllFallback, setUsingChartAllFallback] = useState(false);

  /** Bar/line charts: every project at 0% (common when task updated_at is outside the rolling window). */
  const chartBarsAreZero = (data) => {
    const rows = Array.isArray(data?.project_completion_chart) ? data.project_completion_chart : [];
    if (!rows.length) return true;
    return rows.every((r) => Number(r.task_completion_pct ?? 0) <= 0);
  };

  const looksEmptyForSelectedWindow = (data) => {
    if (!data || typeof data !== 'object') return true;
    const tasksTotal = Number(data?.tasks?.total ?? 0);
    const openActive = Number(data?.tasks?.open_or_active ?? 0);
    const completion = Number(data?.tasks?.completion_rate_pct ?? 0);
    const util = Number(data?.skill_utilization_pct ?? 0);
    const projectRows = Array.isArray(data?.project_completion_chart) ? data.project_completion_chart : [];
    const skillRows = Array.isArray(data?.skill_distribution) ? data.skill_distribution : [];
    return (
      tasksTotal <= 0 &&
      openActive <= 0 &&
      completion <= 0 &&
      util <= 0 &&
      projectRows.length === 0 &&
      skillRows.length === 0
    );
  };

  const loadDashboard = useCallback(async () => {
    try {
      setLoadError(null);
      setUsingAllFallback(false);
      setUsingChartAllFallback(false);
      let data = await analyticsService.getDashboard(timeFrame);
      if (timeFrame !== 'all' && looksEmptyForSelectedWindow(data)) {
        const allData = await analyticsService.getDashboard('all');
        if (!looksEmptyForSelectedWindow(allData)) {
          data = { ...allData, period: 'all' };
          setUsingAllFallback(true);
        }
      } else if (timeFrame !== 'all' && chartBarsAreZero(data)) {
        const allData = await analyticsService.getDashboard('all');
        if (!chartBarsAreZero(allData)) {
          data = {
            ...data,
            project_completion_chart: allData.project_completion_chart,
          };
          setUsingChartAllFallback(true);
        }
      }
      const normalized = data && typeof data === 'object' ? { ...data } : data;
      if (normalized && typeof normalized === 'object') {
        const u = normalized.users && typeof normalized.users === 'object' ? { ...normalized.users } : {};
        const rawDev = Number(u.developers ?? 0);
        const summaryDev = Number(normalized?.performance_summary?.developers_count ?? 0);
        let verifiedDev = Number.isFinite(summaryDev) && summaryDev > 0 ? summaryDev : 0;
        if (!verifiedDev || (Number.isFinite(rawDev) && rawDev > verifiedDev)) {
          try {
            const perf = await analyticsService.getPerformanceReport('all');
            const perfN = Array.isArray(perf?.developers) ? perf.developers.length : 0;
            if (Number.isFinite(perfN) && perfN > 0) verifiedDev = verifiedDev > 0 ? Math.min(verifiedDev, perfN) : perfN;
          } catch {
            /* keep dashboard values if perf endpoint is unavailable */
          }
        }
        if (Number.isFinite(rawDev) && rawDev > 0 && verifiedDev > 0) {
          u.developers = Math.min(rawDev, verifiedDev);
          normalized.users = u;
        } else if (verifiedDev > 0) {
          u.developers = verifiedDev;
          normalized.users = u;
        }
        try {
          const devRows = await userService.getDevelopers();
          const dedupedDevN = dedupePeopleCount(devRows);
          if (Number.isFinite(dedupedDevN) && dedupedDevN > 0) {
            const cur = Number(u.developers ?? 0);
            u.developers = Number.isFinite(cur) && cur > 0 ? Math.min(cur, dedupedDevN) : dedupedDevN;
            normalized.users = u;
          }
        } catch {
          /* keep analytics counts if developers endpoint fails */
        }
      }
      setLiveSummary(normalized);
      setLastUpdated(new Date());
    } catch (err) {
      setLoadError(getApiErrorMessage(err, 'Could not load analytics'));
      setLiveSummary(null);
    }
  }, [timeFrame]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await loadDashboard();
    })();
    const id = setInterval(() => {
      if (!cancelled) loadDashboard();
    }, REFRESH_MS);
    const onVis = () => {
      if (document.visibilityState === 'visible') loadDashboard();
    };
    document.addEventListener('visibilitychange', onVis);
    return () => {
      cancelled = true;
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVis);
    };
  }, [loadDashboard]);

  const skillDistributionData = useMemo(() => {
    const dist = liveSummary?.skill_distribution;
    if (!dist?.length) {
      return {
        labels: ['No data yet'],
        datasets: [
          {
            label: 'Developers',
            data: [1],
            backgroundColor: ['#e5e7eb'],
            borderWidth: 0,
          },
        ],
      };
    }
    return {
      labels: dist.map((x) => x.skill),
      datasets: [
        {
          label: 'Developers with skill',
          data: dist.map((x) => x.developers_with_skill),
          backgroundColor: dist.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
          borderWidth: 2,
          borderColor: '#fff',
        },
      ],
    };
  }, [liveSummary]);

  const projectLineData = useMemo(() => {
    const rows = liveSummary?.project_completion_chart;
    if (!rows?.length) {
      return {
        labels: ['—'],
        datasets: [
          {
            label: 'Task completion %',
            data: [0],
            borderColor: '#3b82f6',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            borderWidth: 2,
            tension: 0.35,
            fill: true,
          },
        ],
      };
    }
    return {
      labels: rows.map((r) => r.label),
      datasets: [
        {
          label: 'Task completion % (by project)',
          data: rows.map((r) => r.task_completion_pct),
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59, 130, 246, 0.12)',
          borderWidth: 2,
          tension: 0.35,
          fill: true,
        },
      ],
    };
  }, [liveSummary]);

  const projectBarData = useMemo(() => {
    const rows = liveSummary?.project_completion_chart;
    if (!rows?.length) {
      return {
        labels: ['—'],
        datasets: [
          {
            label: 'Completed / total tasks',
            data: [0],
            backgroundColor: '#3B82F6',
          },
        ],
      };
    }
    return {
      labels: rows.map((r) => r.label),
      datasets: [
        {
          label: 'Task completion %',
          data: rows.map((r) => r.task_completion_pct),
          backgroundColor: rows.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
          borderWidth: 1,
        },
      ],
    };
  }, [liveSummary]);

  const cardMetrics = useMemo(() => {
    // null = nothing to measure (no tasks in the window), shown as "—" rather than a misleading 0%.
    const tasksInScope = Number(liveSummary?.tasks?.total ?? 0);
    const completionRate = tasksInScope > 0 ? Number(liveSummary?.tasks?.completion_rate_pct || 0) : null;
    const matchAccuracy = Number(liveSummary?.skill_utilization_pct || 0);
    // Average only over projects that actually have tasks in the window; empty projects are not "0% productive".
    const withTasks = (liveSummary?.team_performance || []).filter((p) => Number(p.tasks_total || 0) > 0);
    const teamProductivity = withTasks.length
      ? Math.round(withTasks.reduce((a, p) => a + Number(p.task_completion_pct || 0), 0) / withTasks.length)
      : null;
    return { completionRate, matchAccuracy, teamProductivity, tasksInScope };
  }, [liveSummary]);

  const windowLabel = { week: 'last 7 days', month: 'last 30 days', quarter: 'last 90 days' }[timeFrame] || 'selected window';
  const noActivityHint = `No task activity in the ${windowLabel} — choose “All time” to see overall numbers`;

  const displayedDeveloperCount = useMemo(() => {
    const raw = Number(liveSummary?.users?.developers ?? 0);
    const summary = Number(liveSummary?.performance_summary?.developers_count ?? 0);
    const rawOk = Number.isFinite(raw) && raw > 0;
    const sumOk = Number.isFinite(summary) && summary > 0;
    if (rawOk && sumOk) return Math.min(raw, summary);
    if (sumOk) return summary;
    if (rawOk) return raw;
    return 0;
  }, [liveSummary]);

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'bottom',
        labels: { color: typeof document !== 'undefined' && document.documentElement.classList.contains('dark') ? '#e5e7eb' : '#374151' },
      },
      tooltip: {
        backgroundColor: 'rgba(0, 0, 0, 0.8)',
        titleFont: { size: 14 },
        bodyFont: { size: 13 },
        padding: 12,
        cornerRadius: 6,
      },
    },
  };

  const barChartOptions = {
    ...chartOptions,
    scales: {
      y: {
        beginAtZero: true,
        max: 100,
        ticks: {
          callback: (value) => value + '%',
          color: '#9ca3af',
        },
        grid: { color: 'rgba(107,114,128,0.2)' },
      },
      x: {
        ticks: { color: '#9ca3af', maxRotation: 45, minRotation: 0 },
        grid: { display: false },
      },
    },
  };

  const MetricCard = ({ title, value, subtitle, icon, color }) => (
    <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6 transition-colors">
      <div className="flex items-center">
        {icon ? (
          <div
            className={`w-12 h-12 ${color} rounded-lg flex items-center justify-center mr-4 border border-white/50 dark:border-blue-800/60 shadow-[inset_0_1px_0_rgba(255,255,255,0.25)]`}
          >
          {icon}
        </div>
        ) : null}
        <div>
          <div className="text-2xl font-bold text-gray-900 dark:text-gray-100">{value}</div>
          <div className="text-lg font-medium text-gray-700 dark:text-gray-300 mt-1">{title}</div>
          {subtitle && <div className="text-sm text-gray-500 dark:text-gray-400 mt-1">{subtitle}</div>}
        </div>
      </div>
    </div>
  );

  const downloadPerformanceReportFile = async () => {
    setActionLoading('report');
    try {
      const { blob, filename } = await analyticsService.getPerformanceReportPdf(timeFrame);
      downloadBlob(blob, filename, 'application/pdf');
    } catch (e) {
      await alertBlobError(e, 'Could not download report');
    } finally {
      setActionLoading(null);
    }
  };

  const downloadSkillGapFile = async () => {
    setActionLoading('gap');
    try {
      const { blob, filename } = await analyticsService.getSkillGapPdf();
      downloadBlob(blob, filename, 'application/pdf');
    } catch (e) {
      await alertBlobError(e, 'Could not download skill gap file');
    } finally {
      setActionLoading(null);
    }
  };

  const downloadExport = async (format) => {
    setActionLoading(`export-${format}`);
    try {
      await analyticsService.exportAnalytics(format, timeFrame);
    } catch (e) {
      alert(getApiErrorMessage(e, 'Export failed'));
    } finally {
      setActionLoading(null);
    }
  };

  const downloadHtmlReportForPrint = async () => {
    setActionLoading('print');
    try {
      const [perf, dash, gapDetail] = await Promise.all([
        analyticsService.getPerformanceReport(timeFrame),
        analyticsService.getDashboard(timeFrame),
        analyticsService.getSkillGapDetail(),
      ]);
      let developerProfiles = [];
      try {
        developerProfiles = await userService.getDevelopers();
      } catch {
        developerProfiles = [];
      }
      const dedupedPerfDevelopers = dedupePeopleCount(perf?.developers || []);
      const dashboardDevelopers = Number(dash?.users?.developers ?? 0);
      const summaryDevelopers = Number(dash?.performance_summary?.developers_count ?? 0);
      const candidates = [dedupedPerfDevelopers, dashboardDevelopers, summaryDevelopers].filter(
        (n) => Number.isFinite(n) && n > 0,
      );
      const htmlDevelopersCount = candidates.length ? Math.min(...candidates) : null;
      const esc = (s) =>
        String(s ?? '')
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;');
      /** Rank column must be tier text only (never bare scores like 45). */
      const normalizeRankLabel = (raw, doneN) => {
        const t0 = String(raw ?? '').trim();
        const low = t0.toLowerCase();
        if (!t0 || low === '—' || low === '-' || low === 'none' || low === 'null') {
          return doneN > 0 ? 'Weak' : 'No tasks';
        }
        if (/\bscore\b/i.test(t0) || /^\d+$/.test(t0)) {
          return doneN > 0 ? 'Weak' : 'No tasks';
        }
        if (doneN > 0 && (low === 'no tasks' || low.includes('no task'))) {
          return 'Weak';
        }
        if (low === 'good') return 'Average';
        return t0;
      };
      const safeText = (v, fallback = '') => {
        if (v == null) return fallback;
        const t = String(v).trim();
        if (!t || t.toLowerCase() === 'none' || t === '—' || t === '-') return fallback;
        return t;
      };
      const dedupeDeveloperRowsForHtml = (rows) => {
        const byKey = new Map();
        for (const d of rows || []) {
          const email = String(d?.email ?? '').trim().toLowerCase();
          const nm = String(d?.full_name ?? d?.name ?? '').trim().toLowerCase();
          const key =
            email && email.includes('@') && email !== 'not on file'
              ? `e:${email}`
              : nm
                ? `n:${nm}`
                : `id:${String(d?.id ?? '').trim()}`;
          const prev = byKey.get(key);
          if (!prev) {
            byKey.set(key, { ...d });
            continue;
          }
          const merged = { ...prev };
          for (const f of ['tasks_total', 'tasks_completed', 'tasks_active', 'tasks_in_progress']) {
            merged[f] = Math.max(Number(prev?.[f] ?? 0), Number(d?.[f] ?? 0));
          }
          if (String(d?.full_name ?? '').length > String(prev?.full_name ?? '').length) merged.full_name = d.full_name;
          if ((!prev?.email || String(prev.email).toLowerCase() === 'not on file') && d?.email) merged.email = d.email;
          byKey.set(key, merged);
        }
        return [...byKey.values()];
      };
      const rankLabelFromCompleted = (doneN, distinctDesc) => {
        if (doneN <= 0) return 'No tasks';
        const top = distinctDesc?.[0] || 0;
        const second = distinctDesc?.[1] || 0;
        if (doneN >= top) return 'Excellent';
        if (second > 0 && doneN >= second) return 'Average';
        return 'Weak';
      };
      const perfRowsDeduped = dedupeDeveloperRowsForHtml(perf.developers || []);
      const distinctCompletedDesc = [...new Set(
        perfRowsDeduped
          .map((d) => Number(d?.tasks_completed ?? d?.performance_rank_completed ?? 0))
          .filter((n) => Number.isFinite(n) && n > 0),
      )].sort((a, b) => b - a);
      const devRows = perfRowsDeduped
        .map((d) => {
          const doneN = Number(d.tasks_completed ?? d.performance_rank_completed ?? 0);
          const labelRaw =
            d.performance_display != null && String(d.performance_display).trim() !== ''
              ? String(d.performance_display).trim()
              : d.performance_label != null && String(d.performance_label).trim() !== ''
                ? String(d.performance_label).trim()
                : '';
          let label = rankLabelFromCompleted(doneN, distinctCompletedDesc);
          if (!label) label = normalizeRankLabel(labelRaw, doneN);
          if (!label) label = doneN > 0 ? 'Weak' : 'No tasks';
          const results = `<b>${esc(label)}</b>`;
          return `<tr><td>${esc(d.full_name ?? '')}</td><td>${esc(d.email ?? '')}</td><td>${d.tasks_total ?? '0'}</td><td>${d.tasks_completed ?? '0'}</td><td>${d.tasks_active ?? '0'}</td><td>${d.tasks_in_progress ?? '0'}</td><td>${results}</td></tr>`;
        })
        .join('');
      const projRows = (perf.projects || [])
        .map(
          (p) =>
            `<tr><td>${esc(p.project_title)}</td><td>${esc(p.project_status)}</td><td>${p.progress_pct ?? '—'}%</td><td>${p.task_completion_pct ?? '—'}%</td><td>${p.tasks_completed ?? '—'} / ${p.tasks_total ?? '—'}</td><td>${p.team_size ?? '—'}</td></tr>`,
        )
        .join('');
      const gaps = gapDetail?.gaps || [];
      const gapRows =
        gaps.length === 0
          ? '<tr><td colspan="5">No skill gaps identified (add require_skills to projects to analyze gaps).</td></tr>'
          : gaps
              .map((g) => {
                const avgCell = (() => {
                  const a0 = g.avg_proficiency_0_100;
                  if (typeof a0 === 'number' && Number.isFinite(a0)) return `${esc(String(a0))}%`;
                  const ap = g.avg_proficiency;
                  if (typeof ap === 'number' && Number.isFinite(ap)) return esc(String(ap));
                  if (ap != null && ap !== '' && String(ap).toLowerCase() !== 'nan') return esc(String(ap));
                  return '0';
                })();
                const projCell = esc(
                  g.projects_requiring_display != null && String(g.projects_requiring_display).trim() !== ''
                    ? g.projects_requiring_display
                    : String(g.projects_requiring ?? '0'),
                );
                const pickDevCol = () => {
                  const bad = (t) => {
                    if (!t || t === '—' || t === '-') return true;
                    const l = t.toLowerCase();
                    if (l === 'none' || l === 'null') return true;
                    if (
                      l.includes('no accounts loaded') ||
                      l.includes('verify backend') ||
                      l.includes('.env') ||
                      l.includes('developer profiles') ||
                      l.includes('no user documents') ||
                      l.includes('api connection') ||
                      l.includes('database for this api')
                    )
                      return true;
                    return false;
                  };
                  const looksLikeCountNamesLine = (t) => {
                    const s = String(t).trim();
                    return /^\d+\s*:\s*\S/.test(s) && s.length > 3;
                  };
                  for (const x of [
                    g.developers_count_names_display,
                    g.developers_gap_display,
                    g.developers_with_proficiency,
                  ]) {
                    if (x == null) continue;
                    const t = String(x).trim();
                    if (looksLikeCountNamesLine(t)) {
                      const low = t.toLowerCase();
                      if (
                        low.includes('no user documents') ||
                        low.includes('api connection') ||
                        low.includes('database for this api') ||
                        low === '0: (names unavailable)' ||
                        low === '0: developer'
                      )
                        continue;
                      return t;
                    }
                    if (!bad(t)) return t;
                  }
                  return '';
                };
                let devGap = pickDevCol();
                if (!devGap) {
                  devGap = buildSkillGapLineFromDetail(g);
                }
                const lowGap = String(devGap || '').trim().toLowerCase();
                if (!devGap || lowGap === '0: (names unavailable)' || lowGap === '0: developer') {
                  const fromProfiles = skillGapLineFromDeveloperProfiles(g?.skill, developerProfiles);
                  if (fromProfiles) devGap = fromProfiles;
                }
                const dg = String(devGap || '')
                  .trim()
                  .toLowerCase();
                if (
                  (!devGap ||
                    dg === '0: developer' ||
                    dg === '0: (names unavailable)') &&
                  Array.isArray(gapDetail?.roster_display_names) &&
                  gapDetail.roster_display_names.length
                ) {
                  const head = gapDetail.roster_display_names.slice(0, 120).join(', ');
                  devGap = `0: ${head}`;
                }
                if (!devGap) {
                  devGap =
                    Array.isArray(gapDetail?.roster_display_names) && gapDetail.roster_display_names.length
                      ? `0: ${gapDetail.roster_display_names.slice(0, 120).join(', ')}`
                      : '0: (names unavailable)';
                }
                return `<tr><td>${esc(safeText(g.skill, 'Skill'))}</td><td>${esc(safeText(g.status, 'status'))}</td><td>${esc(devGap)}</td><td>${avgCell}</td><td>${projCell}</td></tr>`;
              })
              .join('');
      const html = `<!DOCTYPE html><html><head><meta charset="utf-8"/><title>Analytics Report</title>
        <style>
          body{font-family:system-ui,sans-serif;padding:24px;color:#111}
          h1{font-size:20px} h2{font-size:16px;margin-top:24px}
          table{border-collapse:collapse;width:100%;margin-top:8px;font-size:12px}
          th,td{border:1px solid #ccc;padding:6px 8px;text-align:left}
          th{background:#f3f4f6}
        </style></head><body>
        <h1>Skill Mapping — Performance &amp; skill gap report</h1>
        <p>Period: ${esc(timeFrame)} · Generated: ${esc(perf.generated_at)}</p>
        <h2>Summary</h2>
        <p>Developers: ${htmlDevelopersCount ?? '—'} · Projects: ${dash?.projects_total ?? '—'} · Tasks done: ${dash?.tasks?.completed ?? '—'} / ${dash?.tasks?.total ?? '—'}</p>
        <h2>Developers</h2>
        <table><thead><tr><th>Name</th><th>Email</th><th>Tasks (scope)</th><th>Completed (done)</th><th>Active</th><th>In progress</th><th>Rank</th></tr></thead><tbody>${devRows}</tbody></table>
        <h2>Projects</h2>
        <table><thead><tr><th>Project</th><th>Status</th><th>Progress %</th><th>Completion %</th><th>Tasks (done / total)</th><th>Team size</th></tr></thead><tbody>${projRows}</tbody></table>
        <h2>Skill gaps (missing / weak)</h2>
        <table><thead><tr><th>Skill</th><th>Status</th><th>Developers (count + names)</th><th>Avg prof. (0–100)</th><th>Projects (titles)</th></tr></thead><tbody>${gapRows}</tbody></table>
        <p>— Open this file in a browser and use Print → Save as PDF (Ctrl+P).</p>
        </body></html>`;
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
      downloadBlob(html, `analytics_report_${timeFrame}_${stamp}.html`, 'text/html;charset=utf-8');
    } catch (e) {
      alert(getApiErrorMessage(e, 'Could not build HTML report'));
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <div className="max-w-7xl mx-auto py-6 px-4 sm:px-6 lg:px-8 min-h-screen bg-gray-50 dark:bg-gray-900 transition-colors">
      <div className="flex justify-between items-center mb-8 flex-wrap gap-4">
        <div>
          <h2 className="text-3xl font-bold text-gray-900 dark:text-gray-100">Analytics Dashboard</h2>
          <p className="text-gray-600 dark:text-gray-400 mt-2">
            Live MongoDB metrics — refreshes every {REFRESH_MS / 1000}s and when you return to this tab. Task charts use
            rolling windows from <code className="text-xs bg-gray-200 dark:bg-gray-700 px-1 rounded">created_at</code> /{' '}
            <code className="text-xs bg-gray-200 dark:bg-gray-700 px-1 rounded">updated_at</code>.
          </p>
          {liveSummary && (
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
              {liveSummary.period === 'all' || !liveSummary.period_start
                ? `Selected range: all time (full task history)`
                : `Selected range: ${timeFrame} · ${liveSummary.period_start} → ${liveSummary.period_end}`}
            </p>
          )}
          {lastUpdated && (
            <p className="text-xs text-gray-500 dark:text-gray-500 mt-1">Last updated: {lastUpdated.toLocaleString()}</p>
          )}
          {usingAllFallback && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">
              No activity found in selected window, showing all-time live data.
            </p>
          )}
          {usingChartAllFallback && !usingAllFallback && (
            <p className="text-xs text-amber-600 dark:text-amber-400 mt-1">
              No per-project completion in this {timeFrame} window (tasks not updated recently) — charts use all-time
              completion; cards still use the selected window.
            </p>
          )}
          {loadError && (
            <p className="text-sm text-red-600 dark:text-red-400 mt-2">{loadError}</p>
          )}
          {liveSummary && (
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
              Live: {displayedDeveloperCount} developers · {liveSummary?.users?.managers ?? 0} PMs ·{' '}
              {liveSummary?.projects_total ?? 0} projects · {liveSummary?.tasks?.open_or_active ?? 0} active tasks · skill
              utilization {liveSummary?.skill_utilization_pct ?? 0}% · project success {liveSummary?.project_success_rate_pct ?? 0}%
              {liveSummary?.skill_gap_percentage != null ? (
                <span className="block mt-1 text-gray-600 dark:text-gray-300">
                  Skill gap index: {liveSummary.skill_gap_percentage}%
                </span>
              ) : null}
            </p>
          )}
        </div>
        <div className="flex space-x-2">
          <button
            type="button"
            onClick={() => setTimeFrame('week')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              timeFrame === 'week'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
            }`}
          >
            Week
          </button>
          <button
            type="button"
            onClick={() => setTimeFrame('month')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              timeFrame === 'month'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
            }`}
          >
            Month
          </button>
          <button
            type="button"
            onClick={() => setTimeFrame('quarter')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              timeFrame === 'quarter'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
            }`}
          >
            Quarter
          </button>
          <button
            type="button"
            onClick={() => setTimeFrame('all')}
            className={`px-4 py-2 rounded-lg font-medium transition-colors ${
              timeFrame === 'all'
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700'
            }`}
          >
            All time
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-8">
        <MetricCard
          title="Completion Rate"
          value={cardMetrics.completionRate == null ? '—' : `${cardMetrics.completionRate}%`}
          subtitle={
            cardMetrics.completionRate == null
              ? noActivityHint
              : liveSummary?.tasks?.scoped_to_period
                ? `Tasks completed ÷ tasks touched in the ${windowLabel}`
                : 'All-time task completion'
          }
          icon={<svg className="w-6 h-6 text-green-600 dark:text-green-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>}
          color="bg-green-50 dark:bg-green-900/30"
        />
        <MetricCard
          title="Match / utilization signal"
          value={`${cardMetrics.matchAccuracy}%`}
          subtitle="Live skill utilization from project requirements vs developer coverage"
          icon={null}
          color="bg-blue-50 dark:bg-blue-900/30"
        />
        <MetricCard
          title="Team productivity"
          value={cardMetrics.teamProductivity == null ? '—' : `${cardMetrics.teamProductivity}%`}
          subtitle={
            cardMetrics.teamProductivity == null
              ? noActivityHint
              : 'Avg task completion % across projects that have tasks'
          }
          icon={<svg className="w-6 h-6 text-purple-600 dark:text-purple-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" /></svg>}
          color="bg-purple-50 dark:bg-purple-900/30"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Skill distribution</h3>
            <span className="px-3 py-1 bg-blue-100 dark:bg-blue-900/40 text-blue-800 dark:text-blue-200 text-sm rounded-full">
              {liveSummary?.tasks?.scoped_to_period ? 'Devs with task activity in range' : 'All developers'}
            </span>
          </div>
          <div className="h-80">
            <Doughnut data={skillDistributionData} options={chartOptions} />
          </div>
        </div>

        <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
          <div className="flex justify-between items-center mb-6">
            <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Project task completion</h3>
            <span className="px-3 py-1 bg-green-100 dark:bg-green-900/40 text-green-800 dark:text-green-200 text-sm rounded-full">
              {timeFrame.charAt(0).toUpperCase() + timeFrame.slice(1)} (rolling)
            </span>
          </div>
          <div className="h-80">
            <Line data={projectLineData} options={chartOptions} />
          </div>
        </div>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6 mb-8">
        <div className="flex justify-between items-center mb-6">
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100">Per-project completion %</h3>
          <span className="px-3 py-1 bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200 text-sm rounded-full">Live tasks</span>
        </div>
        <div className="h-80">
          <Bar data={projectBarData} options={barChartOptions} />
        </div>
        <div className="mt-6 text-center text-sm text-gray-600 dark:text-gray-400">
          {usingChartAllFallback
            ? 'Charts show all-time task completion because nothing completed in the selected rolling window (check task updated_at in MongoDB).'
            : liveSummary?.tasks?.scoped_to_period
              ? 'Per project: completed tasks with updates in the selected window ÷ tasks touched in that window.'
              : 'Per project: all-time completed ÷ all tasks.'}
        </div>
      </div>

      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-sm border border-gray-200 dark:border-gray-700 p-6">
        <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-6">Reports &amp; insights</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <button
            type="button"
            onClick={downloadPerformanceReportFile}
            disabled={actionLoading === 'report'}
            className="bg-blue-50 dark:bg-blue-900/20 hover:bg-blue-100 dark:hover:bg-blue-900/40 text-blue-700 dark:text-blue-300 font-medium py-4 px-6 rounded-xl transition-colors text-left border border-blue-100 dark:border-blue-800 disabled:opacity-50"
          >
            <div className="font-semibold mb-2">
              {actionLoading === 'report' ? 'Preparing…' : 'Download performance report'}
            </div>
            <div className="text-sm text-blue-600 dark:text-blue-400">PDF to your PC — uses selected {timeFrame} window</div>
          </button>
          <button
            type="button"
            onClick={downloadSkillGapFile}
            disabled={actionLoading === 'gap'}
            className="bg-green-50 dark:bg-green-900/20 hover:bg-green-100 dark:hover:bg-green-900/40 text-green-700 dark:text-green-300 font-medium py-4 px-6 rounded-xl transition-colors text-left border border-green-100 dark:border-green-800 disabled:opacity-50"
          >
            <div className="font-semibold mb-2">
              {actionLoading === 'gap' ? 'Preparing…' : 'Download skill gap analysis'}
            </div>
            <div className="text-sm text-green-600 dark:text-green-400">PDF to your PC — org vs project requirements</div>
          </button>
          <div className="bg-purple-50 dark:bg-purple-900/20 border border-purple-100 dark:border-purple-800 rounded-xl p-4 text-purple-800 dark:text-purple-200">
            <div className="font-semibold mb-3">Export analytics data</div>
            <div className="flex flex-col gap-2">
              <button
                type="button"
                onClick={() => downloadExport('json')}
                disabled={actionLoading?.startsWith('export')}
                className="text-left text-sm py-2 px-3 rounded-lg bg-white/80 dark:bg-gray-800/80 hover:bg-white dark:hover:bg-gray-700 disabled:opacity-50"
              >
                {actionLoading === 'export-json' ? '…' : 'Download JSON'}
              </button>
              <button
                type="button"
                onClick={() => downloadExport('csv')}
                disabled={actionLoading?.startsWith('export')}
                className="text-left text-sm py-2 px-3 rounded-lg bg-white/80 dark:bg-gray-800/80 hover:bg-white dark:hover:bg-gray-700 disabled:opacity-50"
              >
                {actionLoading === 'export-csv' ? '…' : 'Download CSV'}
              </button>
              <button
                type="button"
                onClick={downloadHtmlReportForPrint}
                disabled={actionLoading === 'print'}
                className="text-left text-sm py-2 px-3 rounded-lg bg-white/80 dark:bg-gray-800/80 hover:bg-white dark:hover:bg-gray-700 disabled:opacity-50"
              >
                {actionLoading === 'print' ? '…' : 'Download HTML report (print to PDF)'}
              </button>
            </div>
            <p className="text-xs text-purple-600 dark:text-purple-400 mt-2">
              Files save to your Downloads folder. Open the HTML file, then Ctrl+P → Save as PDF.
            </p>
          </div>
        </div>
      </div>

    </div>
  );
};

export default AnalyticsDashboard;
