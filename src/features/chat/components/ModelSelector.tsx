import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import {
  BrainCircuit,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleGauge,
  Search,
  Settings2,
  X,
  Zap,
} from 'lucide-react';
import ContextUsagePopover from '../../../components/Chat/ContextUsagePopover';
import { useURLRouter } from '../../../hooks/useURLRouter';
import type { ModelSpeed, ThinkingLevel } from '../../../services/api';
import { indexModelCatalog } from '../modelCatalogSearch';
import { isImageToolModel, type ChatModel } from '../modelSelection';

interface Props {
  currentModel: string;
  contextUsage?: unknown;
  contextKey?: string;
  models: ChatModel[];
  onModelChange: (model: string) => void;
  thinkingLevel: ThinkingLevel | null;
  onThinkingLevelChange: (level: ThinkingLevel | null) => void;
  serviceTier?: ModelSpeed;
  onServiceTierChange?: (speed: ModelSpeed) => void;
}

type Pane = 'overview' | 'models' | 'effort' | 'speed';
type Choice = { model: ChatModel; title: string; providerName: string };
type ProviderGroup = { id: string; label: string; choices: Choice[] };

const groupPriority = ['chatgpt', 'codex', 'platform'];

function providerRank(id: string) {
  const rank = groupPriority.indexOf(id);
  return rank === -1 ? groupPriority.length : rank;
}

function SourceMark({ source }: { source?: string }) {
  const paths = {
    platform: 'M12 3.8 19 8v8l-7 4.2L5 16V8zM5 8l7 4.2L19 8M12 12.2v8',
    codex: 'm9.5 7-5 5 5 5m5-10 5 5-5 5M13.4 4.8l-2.8 14.4',
    chatgpt: 'M5.2 5.9h13.6v9.5H12l-4.1 3.2v-3.2H5.2zM9 10.7h6',
    key: 'M14 11.5a4 4 0 1 0-3.5-3.5l-6.2 6.2v3.9h3.9v-2.7h2.7z',
  };
  return (
    <span className="agent-model-mark" aria-hidden="true">
      <svg
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d={paths[source as keyof typeof paths] || paths.platform} />
      </svg>
    </span>
  );
}

export function ModelSelector({
  currentModel,
  contextUsage,
  contextKey,
  models,
  onModelChange,
  thinkingLevel,
  onThinkingLevelChange,
  serviceTier = 'standard',
  onServiceTierChange,
}: Props) {
  const { t, i18n } = useTranslation();
  const { navigateToSettings } = useURLRouter();
  const id = useId();
  const anchor = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const returnTo = useRef<Exclude<Pane, 'overview'>>('models');
  const [position, setPosition] = useState<{
    left: number;
    bottom?: number;
    top?: number;
    maxHeight?: number;
  } | null>(null);
  const [pane, setPane] = useState<Pane>('overview');
  const [search, setSearch] = useState('');
  const choices = useMemo<Choice[]>(
    () =>
      models
        .filter((model) => !isImageToolModel(model))
        .map((model) => ({
          model,
          title: model.titleKey ? t(model.titleKey, { defaultValue: model.title }) : model.title,
          providerName: model.subtitleKey
            ? t(model.subtitleKey, { defaultValue: model.subtitle })
            : model.subtitle || model.provider,
        })),
    [models, t]
  );
  const groupIndexes = useMemo(() => {
    const groups = new Map<string, ProviderGroup>();
    for (const choice of choices) {
      const { source, provider } = choice.model;
      const id = source === 'key' ? 'key/' + provider : source;
      if (!groups.has(id)) {
        const label =
          source === 'key' && choice.providerName
            ? choice.providerName
            : t('agentSettings.sources.' + source, { defaultValue: source });
        groups.set(id, { id, label, choices: [] });
      }
      groups.get(id)?.choices.push(choice);
    }
    return Array.from(groups.values())
      .sort((left, right) => providerRank(left.id) - providerRank(right.id))
      .map((group) => ({
        group,
        matching: indexModelCatalog(group.choices, (choice) => ({
          names: [choice.title, choice.model.id.split('/').at(-1) || '', choice.providerName],
          descriptions: [group.label, choice.model.provider],
        })),
      }));
  }, [choices, t]);
  const showSearch = choices.length > 4;
  const visibleGroups =
    pane === 'models'
      ? groupIndexes
          .map(({ group, matching }) => ({
            ...group,
            choices: matching(showSearch ? search : ''),
          }))
          .filter((group) => group.choices.length > 0)
      : [];
  const current = choices.find(({ model }) => model.id === currentModel);
  const active = current?.model;
  const numberFormat = new Intl.NumberFormat(i18n.language);
  const shownEffort = thinkingLevel || active?.defaultThinkingLevel;
  const effortLabel = shownEffort
    ? t('models.thinkingLevels.' + shownEffort)
    : t('agentModel.defaultEffort');
  const speedLabel = t('agentSettings.speeds.' + serviceTier);
  const label =
    current?.title || currentModel.replace(/^(?:chatgpt|codex)\//, '') || t('models.choose');
  const title = {
    overview: t('agentSettings.pickerTitle'),
    models: t('models.choose'),
    effort: t('models.thinkingLevel'),
    speed: t('agentSettings.speed'),
  }[pane];
  const place = () => {
    const box = anchor.current?.getBoundingClientRect();
    if (!box) return;
    const { innerWidth: width, innerHeight: height } = window;
    if (width <= 600) {
      const view = window.visualViewport;
      const bottom = view ? Math.max(0, height - view.height - view.offsetTop) : 0;
      setPosition({ left: 0, bottom, maxHeight: Math.min(680, (view?.height ?? height) * 0.84) });
      return;
    }
    const above = box.top - 20;
    const below = height - box.bottom - 20;
    const left = Math.max(12, Math.min(width - 364, box.right - 352));
    const maxHeight = Math.min(525, height - 24);
    if (above >= 188 && (above >= below || above >= maxHeight)) {
      setPosition({ left, bottom: height - box.top + 8, maxHeight: Math.min(maxHeight, above) });
    } else if (below >= 188) {
      setPosition({ left, top: box.bottom + 8, maxHeight: Math.min(maxHeight, below) });
    } else {
      setPosition({ left, top: 12, maxHeight });
    }
  };
  const close = () => {
    setPosition(null);
    trigger.current?.focus();
  };
  const open = position !== null;
  useEffect(() => {
    if (!open) return;
    window.addEventListener('resize', place);
    window.visualViewport?.addEventListener('resize', place);
    return () => {
      window.removeEventListener('resize', place);
      window.visualViewport?.removeEventListener('resize', place);
    };
  }, [open]);
  useEffect(() => {
    if (!open || !panel.current) return;
    const container = panel.current;
    const coarse = window.matchMedia('(pointer: coarse), (max-width: 600px)').matches;
    const preferred =
      pane === 'overview'
        ? container.querySelector<HTMLElement>('[data-picker-pane="' + returnTo.current + '"]')
        : pane === 'models' && !coarse && showSearch
          ? container.querySelector<HTMLInputElement>('input')
          : container.querySelector<HTMLElement>('[data-picker-choice][aria-pressed="true"]');
    const focus =
      preferred || container.querySelector<HTMLElement>('[data-picker-choice]') || container;
    focus.focus();
  }, [open, pane, showSearch]);

  function drill(next: Exclude<Pane, 'overview'>) {
    returnTo.current = next;
    setSearch('');
    setPane(next);
  }

  function pickerKeys(event: KeyboardEvent<HTMLDivElement>) {
    if (event.nativeEvent.isComposing) return;
    const container = event.currentTarget;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      if (pane === 'overview') close();
      else setPane('overview');
      return;
    }
    if (event.key === 'Tab') {
      const controls = Array.from(
        container.querySelectorAll<HTMLElement>('button:not(:disabled), input, a[href]')
      );
      const edge = event.shiftKey ? controls[0] : controls.at(-1);
      if (event.target === edge || event.target === container) {
        event.preventDefault();
        (event.shiftKey ? controls.at(-1) : controls[0])?.focus();
      }
      return;
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    if (event.target instanceof HTMLInputElement && (event.key === 'Home' || event.key === 'End'))
      return;
    const rows = Array.from(
      container.querySelectorAll<HTMLElement>('[data-picker-choice]:not(:disabled)')
    );
    if (!rows.length) return;
    const currentRow = rows.indexOf(document.activeElement as HTMLElement);
    let next = event.key === 'ArrowUp' || event.key === 'End' ? rows.length - 1 : 0;
    if (currentRow >= 0 && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      next = (currentRow + (event.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length;
    }
    event.preventDefault();
    rows[next]?.focus();
  }
  return (
    <div ref={anchor} className="agent-model-anchor">
      <button
        ref={trigger}
        type="button"
        className="model-name-trigger agent-model-trigger"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={id}
        onClick={() => {
          setSearch('');
          if (open) {
            close();
          } else {
            returnTo.current = 'models';
            setPane(active ? 'overview' : 'models');
            place();
          }
        }}
      >
        {active && <SourceMark source={active.source} />}
        <span className="model-btn-name">{label}</span>
        {active?.thinkingLevels.length ? (
          <small className="agent-model-current-effort">{effortLabel}</small>
        ) : null}
        {serviceTier !== 'standard' && <Zap size={14} />}
        <ChevronDown size={14} />
      </button>
      <ContextUsagePopover
        key={contextKey || currentModel}
        value={contextUsage}
        className="model-context-trigger"
        hoverTarget={anchor}
        suppressed={open}
        onOpen={() => setPosition(null)}
      >
        <CircleGauge size={16} />
      </ContextUsagePopover>
      {position &&
        createPortal(
          <div
            className="agent-picker-layer"
            onPointerDown={(event) => {
              if (event.target === event.currentTarget) close();
            }}
          >
            <div
              role="dialog"
              aria-modal="true"
              id={id}
              aria-labelledby={id + '-heading'}
              tabIndex={-1}
              ref={panel}
              className="agent-model-panel"
              style={position}
              onKeyDown={pickerKeys}
            >
              <div className="agent-picker-head">
                {pane !== 'overview' && (
                  <button
                    type="button"
                    onClick={() => setPane('overview')}
                    aria-label={t('agentSettings.back')}
                  >
                    <ChevronLeft className="agent-picker-chevron" size={18} aria-hidden="true" />
                  </button>
                )}
                <h3 id={id + '-heading'}>{title}</h3>
                <button type="button" onClick={close} aria-label={t('common.close')}>
                  <X size={18} aria-hidden="true" />
                </button>
              </div>
              {pane === 'overview' && (
                <>
                  <div className="agent-model-list">
                    <button
                      type="button"
                      data-picker-choice
                      data-picker-pane="models"
                      onClick={() => drill('models')}
                    >
                      <SourceMark source={active?.source ?? 'platform'} />
                      <span className="agent-model-row-copy">
                        <small>{t('think.presentation.model')}</small>
                        <strong>{label}</strong>
                      </span>
                      <ChevronRight className="agent-picker-chevron" size={16} aria-hidden="true" />
                    </button>
                    {!!active?.thinkingLevels.length && (
                      <button
                        type="button"
                        data-picker-choice
                        data-picker-pane="effort"
                        onClick={() => drill('effort')}
                      >
                        <span className="agent-model-mark">
                          <BrainCircuit size={17} aria-hidden="true" />
                        </span>
                        <span className="agent-model-row-copy">
                          <small>{t('models.thinkingLevel')}</small>
                          <strong>{effortLabel}</strong>
                        </span>
                        <ChevronRight
                          className="agent-picker-chevron"
                          size={16}
                          aria-hidden="true"
                        />
                      </button>
                    )}
                    {!!onServiceTierChange && !!active && active.serviceTiers.length > 1 && (
                      <button
                        type="button"
                        data-picker-choice
                        data-picker-pane="speed"
                        onClick={() => drill('speed')}
                      >
                        <span className="agent-model-mark">
                          <Zap size={17} aria-hidden="true" />
                        </span>
                        <span className="agent-model-row-copy">
                          <small>{t('agentSettings.speed')}</small>
                          <strong>{speedLabel}</strong>
                        </span>
                        <ChevronRight
                          className="agent-picker-chevron"
                          size={16}
                          aria-hidden="true"
                        />
                      </button>
                    )}
                  </div>
                  {(active?.contextWindow || active?.maxTokens) && (
                    <dl className="agent-picker-capacity">
                      {active.contextWindow && (
                        <div>
                          <dt>{t('agentModel.contextWindow')}</dt>
                          <dd>{numberFormat.format(active.contextWindow)}</dd>
                        </div>
                      )}
                      {active.maxTokens && (
                        <div>
                          <dt>{t('agentModel.maxTokens')}</dt>
                          <dd>{numberFormat.format(active.maxTokens)}</dd>
                        </div>
                      )}
                    </dl>
                  )}
                </>
              )}
              {pane === 'models' && (
                <>
                  {showSearch && (
                    <label className="agent-model-search">
                      <Search size={16} aria-hidden="true" />
                      <input
                        aria-label={t('agentSettings.search')}
                        placeholder={t('agentSettings.search')}
                        type="search"
                        value={search}
                        maxLength={160}
                        onChange={(event) => setSearch(event.target.value)}
                      />
                    </label>
                  )}
                  {!active && currentModel && (
                    <p className="agent-model-unavailable" role="status">
                      {t('agentSettings.modelUnavailable')}
                    </p>
                  )}
                  <div className="agent-model-list">
                    {visibleGroups.map((group) => (
                      <section key={group.id}>
                        <h4>{group.label}</h4>
                        {group.choices.map(({ model, title: modelTitle, providerName }) => (
                          <button
                            type="button"
                            key={model.id}
                            aria-pressed={model.id === currentModel}
                            data-picker-choice
                            onClick={() => {
                              onModelChange(model.id);
                              close();
                            }}
                          >
                            <SourceMark source={model.source} />
                            <span className="agent-model-row-copy">
                              <strong>{modelTitle}</strong>
                              {providerName && providerName !== group.label && (
                                <small>{providerName}</small>
                              )}
                            </span>
                            {model.id === currentModel && <Check size={17} aria-hidden="true" />}
                          </button>
                        ))}
                      </section>
                    ))}
                    {!visibleGroups.length && (
                      <p className="agent-model-unavailable" role="status">
                        {t('agentSettings.noModels')}
                      </p>
                    )}
                  </div>
                </>
              )}
              {pane === 'effort' && (
                <div className="agent-model-list">
                  {[null, ...(active?.thinkingLevels || [])].map((effort) => (
                    <button
                      type="button"
                      key={effort ?? 'default'}
                      data-picker-choice
                      aria-pressed={thinkingLevel === effort}
                      onClick={() => {
                        onThinkingLevelChange(effort);
                        close();
                      }}
                    >
                      <span className="agent-model-row-copy">
                        {effort
                          ? t('models.thinkingLevels.' + effort)
                          : t('agentModel.defaultEffort')}
                      </span>
                      {thinkingLevel === effort && <Check size={17} aria-hidden="true" />}
                    </button>
                  ))}
                </div>
              )}
              {pane === 'speed' && (
                <>
                  <p className="agent-model-unavailable">{t('agentSettings.speedUsage')}</p>
                  <div className="agent-model-list">
                    {active?.serviceTiers.map((speed) => (
                      <button
                        type="button"
                        key={speed}
                        data-picker-choice
                        aria-pressed={serviceTier === speed}
                        onClick={() => {
                          onServiceTierChange?.(speed);
                          close();
                        }}
                      >
                        <span className="agent-model-row-copy">
                          {t('agentSettings.speeds.' + speed)}
                        </span>
                        {serviceTier === speed && <Check size={17} aria-hidden="true" />}
                      </button>
                    ))}
                  </div>
                </>
              )}
              <div className="agent-picker-footer">
                <a
                  href={new URL('#settings/models', window.location.href).href}
                  onClick={(event) => {
                    if (!event.metaKey && !event.ctrlKey && !event.altKey && !event.shiftKey) {
                      event.preventDefault();
                      navigateToSettings('models', true);
                    }
                    close();
                  }}
                >
                  <Settings2 size={16} />
                  {t('agentSettings.manage')}
                </a>
              </div>
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}

export default ModelSelector;
