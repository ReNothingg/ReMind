import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ArrowLeft,
  BrainCircuit,
  Check,
  Link2,
  Lock,
  Plus,
  Store,
  Trash2,
  type LucideIcon,
} from 'lucide-react';
import {
  apiService,
  type ComposerToolOption,
  type Mind,
  type MindCategory,
  type MindPayload,
  type MindVisibility,
} from '../../services/api';
import { cn } from '../../utils/cn';
import { fetchApi } from '../../services/api/transport';
import { personalSkillEndpoint, skillReferencePrefix, type ImportedSkill } from '../plugins/skillPackage';
import { getMindErrorMessage } from './errorMessages';

type MindEditorPageProps = {
  editingMindId?: string | null;
  isAuthenticated: boolean;
  onCancel: () => void;
  onOpenAuth: () => void;
  onSaved: (mind: Mind) => void;
};

type FormState = {
  category: string;
  description: string;
  instructions: string;
  name: string;
  allow_external_use: boolean;
  skill_ids: string[] | null;
  custom_skills: NonNullable<Mind['custom_skills']>;
  starters: string[];
  visibility: MindVisibility;
};

const DEFAULT_FORM: FormState = {
  category: 'general',
  description: '',
  instructions: '',
  name: '',
  allow_external_use: false,
  skill_ids: null,
  custom_skills: [],
  starters: ['', '', ''],
  visibility: 'private',
};

const VISIBILITY_OPTIONS: Array<{
  icon: LucideIcon;
  id: MindVisibility;
  labelKey: string;
}> = [
  { id: 'private', labelKey: 'minds.visibility.private', icon: Lock },
  { id: 'link', labelKey: 'minds.visibility.linkLong', icon: Link2 },
  { id: 'store', labelKey: 'minds.visibility.store', icon: Store },
];

function useMindErrorMessages() {
  const { t } = useTranslation();
  return useMemo(
    () => ({
      authRequired: t('minds.errors.authRequired'),
      accessDenied: t('minds.errors.accessDenied'),
      notFound: t('minds.errors.notFound'),
      rateLimited: t('minds.errors.rateLimited'),
    }),
    [t]
  );
}

function normalizeStarters(starters: string[]): string[] {
  const seen = new Set<string>();
  const normalized: string[] = [];
  for (const rawStarter of starters) {
    const starter = rawStarter.trim().replace(/\s+/g, ' ');
    if (!starter) continue;
    const key = starter.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    normalized.push(starter);
  }
  return normalized.slice(0, 6);
}

function toFormState(mind: Mind): FormState {
  return {
    category: mind.category || 'general',
    description: mind.description || '',
    instructions: mind.instructions || '',
    name: mind.name || '',
    allow_external_use: mind.allow_external_use === true,
    skill_ids: mind.skill_ids ?? null,
    custom_skills: mind.custom_skills ?? [],
    starters: mind.starters.length > 0 ? [...mind.starters, ''].slice(0, 6) : ['', '', ''],
    visibility: mind.visibility,
  };
}

export default function MindEditorPage({
  editingMindId,
  isAuthenticated,
  onCancel,
  onOpenAuth,
  onSaved,
}: MindEditorPageProps) {
  const { t } = useTranslation();
  const mindErrorMessages = useMindErrorMessages();
  const [categories, setCategories] = useState<MindCategory[]>([]);
  const [skills, setSkills] = useState<ComposerToolOption[]>([]);
  const [library, setLibrary] = useState<ImportedSkill[]>([]);
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [loading, setLoading] = useState(Boolean(editingMindId));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const isEditing = Boolean(editingMindId);

  useEffect(() => {
    let cancelled = false;

    const loadEditorData = async () => {
      setError('');
      setLoading(Boolean(editingMindId));
      try {
        const [categoryList, editingMind, catalog, imported] = await Promise.all([
          apiService.listMindCategories(),
          editingMindId ? apiService.getMind(editingMindId) : Promise.resolve(null),
          apiService.listModelCatalog(),
          isAuthenticated ? fetchApi<{ skills: ImportedSkill[] }>(personalSkillEndpoint)
            .catch(() => ({ skills: [] })) : Promise.resolve({ skills: [] }),
        ]);
        if (cancelled) return;

        setCategories(categoryList);
        setSkills(catalog.tools);
        setLibrary(imported.skills);
        if (editingMind) {
          if (!editingMind.can_edit) {
            setError(t('minds.errors.editAccess'));
          } else {
            setForm(toFormState(editingMind));
          }
        }
      } catch (loadError) {
        console.error('Failed to load mind editor data', loadError);
        if (!cancelled) {
          setError(getMindErrorMessage(loadError, t('minds.errors.editorLoad'), mindErrorMessages));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void loadEditorData();
    return () => {
      cancelled = true;
    };
  }, [editingMindId, mindErrorMessages, isAuthenticated, t]);

  const normalizedStarters = useMemo(() => normalizeStarters(form.starters), [form.starters]);

  const validationError = useMemo(() => {
    if (form.name.trim().length < 2) return t('minds.validation.name');
    if (form.description.trim().length < 8) return t('minds.validation.description');
    if (form.instructions.trim().length < 16) return t('minds.validation.instructions');
    const names = form.custom_skills.map((skill) => skill.name.trim().toLocaleLowerCase());
    if (
      new Set(names).size !== names.length ||
      form.custom_skills.some((skill) => !skill.name.trim() || !skill.instructions.trim())
    )
      return t('mindSkills.invalid');
    if (form.visibility === 'store' && !form.category) return t('minds.validation.category');
    return '';
  }, [form, t]);

  const updateStarter = useCallback((index: number, value: string) => {
    setForm((current) => {
      const starters = [...current.starters];
      starters[index] = value;
      return { ...current, starters };
    });
  }, []);

  const addStarter = useCallback(() => {
    setForm((current) => {
      if (current.starters.length >= 6) return current;
      return { ...current, starters: [...current.starters, ''] };
    });
  }, []);

  const removeStarter = useCallback((index: number) => {
    setForm((current) => {
      const starters = current.starters.filter((_starter, starterIndex) => starterIndex !== index);
      return { ...current, starters: starters.length > 0 ? starters : [''] };
    });
  }, []);

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!isAuthenticated) {
        onOpenAuth();
        return;
      }
      if (validationError) {
        setError(validationError);
        return;
      }

      const payload: MindPayload = {
        name: form.name.trim(),
        description: form.description.trim(),
        instructions: form.instructions.trim(),
        starters: normalizedStarters,
        skill_ids: form.skill_ids,
        allow_external_use: form.allow_external_use,
        custom_skills: form.custom_skills,
        category: form.category,
        visibility: form.visibility,
      };

      setSaving(true);
      setError('');
      try {
        const savedMind = editingMindId
          ? await apiService.updateMind(editingMindId, payload)
          : await apiService.createMind(payload);
        onSaved(savedMind);
      } catch (saveError) {
        console.error('Failed to save mind', saveError);
        setError(getMindErrorMessage(saveError, t('minds.errors.save'), mindErrorMessages));
      } finally {
        setSaving(false);
      }
    },
    [
      editingMindId,
      form,
      isAuthenticated,
      mindErrorMessages,
      normalizedStarters,
      onOpenAuth,
      onSaved,
      t,
      validationError,
    ]
  );

  if (!isAuthenticated) {
    return (
      <section className="mind-editor-page">
        <div className="mind-auth-required">
          <BrainCircuit size={32} />
          <h1>{t('minds.editor.authTitle')}</h1>
          <button type="button" className="mind-create-button" onClick={onOpenAuth}>
            {t('auth.login')}
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="mind-editor-page">
      <div className="mind-editor-heading">
        <button type="button" className="mind-back-button" onClick={onCancel}>
          <ArrowLeft size={18} />
          {t('minds.editor.back')}
        </button>
        <div>
          <div className="minds-title-row">
            <BrainCircuit size={30} />
            <h1>{isEditing ? t('minds.editor.editTitle') : t('minds.editor.createTitle')}</h1>
          </div>
          <p>{isEditing ? t('minds.editor.editSubtitle') : t('minds.editor.createSubtitle')}</p>
        </div>
      </div>

      {loading ? (
        <div className="mind-empty-state">{t('minds.editor.loading')}</div>
      ) : (
        <form className="mind-editor-form" onSubmit={(event) => void handleSubmit(event)}>
          <div className="mind-form-main">
            <label className="mind-field">
              <span>{t('minds.editor.fields.name')}</span>
              <input
                value={form.name}
                onChange={(event) =>
                  setForm((current) => ({ ...current, name: event.target.value }))
                }
                placeholder={t('minds.editor.placeholders.name')}
                maxLength={80}
                required
              />
            </label>

            <label className="mind-field">
              <span>{t('minds.editor.fields.description')}</span>
              <textarea
                value={form.description}
                onChange={(event) =>
                  setForm((current) => ({ ...current, description: event.target.value }))
                }
                placeholder={t('minds.editor.placeholders.description')}
                maxLength={280}
                rows={3}
                required
              />
            </label>

            <label className="mind-field">
              <span>{t('minds.editor.fields.instructions')}</span>
              <textarea
                value={form.instructions}
                onChange={(event) =>
                  setForm((current) => ({ ...current, instructions: event.target.value }))
                }
                placeholder={t('minds.editor.placeholders.instructions')}
                maxLength={8000}
                rows={10}
                required
              />
            </label>

            <div className="mind-field">
              <span>{t('mindSkills.title')}</span>
              <label className="mind-skill-option">
                <input
                  type="checkbox"
                  checked={form.skill_ids === null}
                  onChange={(event) => {
                    const automatic = event.currentTarget.checked;
                    setForm((current) => ({ ...current, skill_ids: automatic ? null : [] }));
                  }}
                />
                {t('mindSkills.automatic')}
              </label>
              {form.skill_ids !== null && (
                <div className="mind-skill-grid">
                  {[
                    ...skills.map(({ id, titleKey }) => ({ id, label: t(titleKey) })),
                    ...library.map(({ name }) => ({ id: skillReferencePrefix + name, label: name })),
                  ].map((skill) => (
                    <label className="mind-skill-option" key={skill.id}>
                      <input
                        type="checkbox"
                        checked={form.skill_ids?.includes(skill.id) || false}
                        onChange={(event) => {
                          const checked = event.currentTarget.checked;
                          setForm((current) => ({
                            ...current,
                            skill_ids: checked
                              ? [...(current.skill_ids || []), skill.id]
                              : (current.skill_ids || []).filter((id) => id !== skill.id),
                          }));
                        }}
                      />
                      {skill.label}
                    </label>
                  ))}
                </div>
              )}
              {form.custom_skills.map((skill, index) => (
                <fieldset className="mind-field mind-custom-skill" key={index}>
                  <input
                    aria-label={t('mindSkills.name')}
                    placeholder={t('mindSkills.name')}
                    value={skill.name}
                    maxLength={80}
                    onChange={(event) => {
                      const name = event.currentTarget.value;
                      setForm((current) => ({
                        ...current,
                        custom_skills: current.custom_skills.map((entry, i) =>
                          i === index ? { ...entry, name } : entry
                        ),
                      }));
                    }}
                  />
                  <textarea
                    aria-label={t('mindSkills.instructions')}
                    placeholder={t('mindSkills.instructions')}
                    rows={4}
                    maxLength={4000}
                    value={skill.instructions}
                    onChange={(event) => {
                      const instructions = event.currentTarget.value;
                      setForm((current) => ({
                        ...current,
                        custom_skills: current.custom_skills.map((entry, i) =>
                          i === index ? { ...entry, instructions } : entry
                        ),
                      }));
                    }}
                  />
                  <button
                    type="button"
                    className="mind-secondary-action"
                    onClick={() =>
                      setForm((current) => ({
                        ...current,
                        custom_skills: current.custom_skills.filter((_, i) => i !== index),
                      }))
                    }
                  >
                    <Trash2 size={16} />
                    {t('mindSkills.remove')}
                  </button>
                </fieldset>
              ))}
              <button
                type="button"
                className="mind-secondary-action"
                disabled={form.custom_skills.length >= 6}
                onClick={() =>
                  setForm((current) => ({
                    ...current,
                    custom_skills: [...current.custom_skills, { name: '', instructions: '' }],
                  }))
                }
              >
                <Plus size={16} />
                {t('mindSkills.add')}
              </button>
            </div>
            <div className="mind-field">
              <span>{t('minds.editor.fields.starters')}</span>
              <div className="mind-starter-editor">
                {form.starters.map((starter, index) => (
                  <div key={`${index}-${form.starters.length}`} className="mind-starter-row">
                    <input
                      value={starter}
                      onChange={(event) => updateStarter(index, event.target.value)}
                      placeholder={t('minds.editor.placeholders.starter')}
                      maxLength={120}
                    />
                    <button
                      type="button"
                      className="mind-icon-action"
                      onClick={() => removeStarter(index)}
                      aria-label={t('minds.editor.removeStarter')}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))}
              </div>
              <button
                type="button"
                className="mind-secondary-action"
                onClick={addStarter}
                disabled={form.starters.length >= 6}
              >
                <Plus size={16} />
                {t('minds.editor.addStarter')}
              </button>
            </div>
          </div>

          <aside className="mind-form-side">
            <div className="mind-side-block">
              <span>{t('minds.editor.access')}</span>
              <div className="mind-visibility-list">
                {VISIBILITY_OPTIONS.map((option) => {
                  const Icon = option.icon;
                  return (
                    <button
                      key={option.id}
                      type="button"
                      className={cn(form.visibility === option.id && 'active')}
                      onClick={() =>
                        setForm((current) => ({
                          ...current,
                          visibility: option.id,
                          category:
                            option.id === 'store' && !current.category
                              ? 'general'
                              : current.category,
                        }))
                      }
                    >
                      <Icon size={17} />
                      {t(option.labelKey)}
                    </button>
                  );
                })}
              </div>
            </div>

            {form.visibility !== 'private' && (
              <div className="mind-side-block">
                <label className="mind-skill-option">
                  <input
                    type="checkbox"
                    checked={form.allow_external_use}
                    onChange={(e) => {
                      const allow = e.target.checked;
                      setForm((current) => ({ ...current, allow_external_use: allow }));
                    }}
                  />
                  {t('mindSkills.external')}
                </label>
                <p>{t('mindSkills.externalHelp')}</p>
              </div>
            )}
            {form.visibility === 'store' && (
              <div className="mind-side-block">
                <span>{t('minds.editor.category')}</span>
                <div className="mind-category-select-grid">
                  {categories.map((category) => (
                    <button
                      key={category.id}
                      type="button"
                      className={cn(form.category === category.id && 'active')}
                      onClick={() => setForm((current) => ({ ...current, category: category.id }))}
                    >
                      {t(`minds.categories.${category.id}`, { defaultValue: category.label })}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="mind-side-block">
              <span>{t('minds.editor.check')}</span>
              <div className="mind-check-list">
                <div className={cn(!validationError && 'ready')}>
                  <Check size={16} />
                  {t('minds.editor.basicReady')}
                </div>
                <div className={cn(normalizedStarters.length > 0 && 'ready')}>
                  <Check size={16} />
                  {t('minds.editor.startersReady')}
                </div>
              </div>
            </div>

            {error && <div className="mind-error">{error}</div>}

            <button type="submit" className="mind-save-button" disabled={saving}>
              {saving
                ? t('minds.editor.saving')
                : isEditing
                  ? t('minds.editor.saveChanges')
                  : t('minds.editor.createAction')}
            </button>
          </aside>
        </form>
      )}
    </section>
  );
}
