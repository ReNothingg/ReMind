import type { GitHubAgentActivity } from '../../services/api';

export type Translate = (key: string, options?: Record<string, unknown>) => string;

function formatCount(value: number | undefined, fallback = 0): string {
    return String(Number.isFinite(value) ? value : fallback);
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function asString(value: unknown): string {
    return typeof value === 'string' ? value : '';
}

function asNumber(value: unknown): number | undefined {
    return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

export function taskStatusLabel(t: Translate, status?: string): string {
    switch (status) {
        case 'planning':
            return t('github.taskStatus.planning');
        case 'planned':
            return t('github.taskStatus.planned');
        case 'running':
            return t('github.taskStatus.running');
        case 'pull_request_opened':
            return t('github.taskStatus.pullRequestOpened');
        case 'completed_no_changes':
            return t('github.taskStatus.completedNoChanges');
        case 'error':
            return t('github.taskStatus.error');
        default:
            return t('github.taskStatus.idle');
    }
}

export function activityTitle(t: Translate, item: GitHubAgentActivity): string {
    const code = item.code || 'unknown';
    return t(`github.activity.codes.${code}`, {
        defaultValue: t('github.activity.codes.unknown'),
    });
}

export function activityDetail(t: Translate, item: GitHubAgentActivity): string {
    const meta = isRecord(item.meta) ? item.meta : {};
    switch (item.code) {
        case 'repoMapLoaded':
            return t('github.activity.details.repoMapLoaded', {
                directories: formatCount(asNumber(meta.directories)),
                files: formatCount(asNumber(meta.files)),
            });
        case 'candidateFilesSelected':
        case 'plannedFilesLoaded':
        case 'fileContextLoaded':
            return t('github.activity.details.filesCount', {
                count: asNumber(meta.count) ?? 0,
            });
        case 'aiProviderJsonParsed':
            return t('github.activity.details.aiProviderJsonParsed', {
                chars: formatCount(asNumber(meta.response_chars)),
            });
        case 'aiProviderInvalidJson':
            return t('github.activity.details.aiProviderInvalidJson', {
                chars: formatCount(asNumber(meta.response_chars)),
            });
        case 'aiProviderRequestFailed':
        case 'aiProviderTextRequestFailed':
        case 'editorFailed':
            return asString(meta.message);
        case 'commitCreated':
            return t('github.activity.details.commitCreated', {
                branch: asString(meta.branch),
            });
        case 'diffLoaded':
            return t('github.activity.details.diffLoaded', {
                files: formatCount(asNumber(meta.files)),
            });
        case 'noChanges':
            return asString(meta.reason);
        case 'pullRequestOpened':
            return t('github.activity.details.pullRequestOpened', {
                number: formatCount(asNumber(meta.number)),
            });
        default:
            return '';
    }
}

export function activityPaths(item: GitHubAgentActivity): string[] {
    const meta = isRecord(item.meta) ? item.meta : {};
    return Array.isArray(meta.paths)
        ? meta.paths.filter((path): path is string => typeof path === 'string' && path.length > 0)
        : [];
}

export function activityPreview(item: GitHubAgentActivity): string {
    const meta = isRecord(item.meta) ? item.meta : {};
    return asString(meta.response_preview);
}

export function localizedAgentMessage(t: Translate, value?: string | null): string {
    if (!value) {
        return '';
    }

    const fallbackMap: Record<string, string> = {
        'Prepare a focused code change in a pull request.': 'github.plan.fallbacks.summary',
        'Inspect repository map': 'github.plan.fallbacks.inspectTitle',
        'Use the selected files as the first editing context.': 'github.plan.fallbacks.inspectDetails',
        'Generate code edits': 'github.plan.fallbacks.editTitle',
        'Apply a small, reviewable change on a new branch.': 'github.plan.fallbacks.editDetails',
        'Open pull request': 'github.plan.fallbacks.prTitle',
        'Show the generated diff and create a PR against the base branch.': 'github.plan.fallbacks.prDetails',
        'The AI planner could not run; selected files are heuristic.': 'github.plan.fallbacks.plannerFallbackRisk',
        'AI editor did not return JSON edits.': 'github.errors.editorInvalidJson',
    };
    const key = fallbackMap[value];
    return key ? t(key) : value;
}

export function formatMapStats(files?: number, directories?: number): { files: string; directories: string } {
    return {
        files: formatCount(files),
        directories: formatCount(directories),
    };
}
