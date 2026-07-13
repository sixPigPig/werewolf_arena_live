import { useMemo } from "react";
import { useAdminSession } from "@/features/auth/session-context";
import { archiveAdminRuleSet, createAdminRuleSet, duplicateAdminRuleSet, getAdminRuleSet, getRuleSetOptions, listAdminRuleSets, publishAdminRuleSet, restoreAdminRuleSet, setDefaultAdminRuleSet, updateAdminRuleSetDraft, validateAdminRuleSet } from "./api";
import { archivePreviewRuleSet, createPreviewRuleSet, duplicatePreviewRuleSet, getPreviewRuleSet, getPreviewRuleSetOptions, listPreviewRuleSets, publishPreviewRuleSet, restorePreviewRuleSet, setDefaultPreviewRuleSet, updatePreviewRuleSetDraft, validatePreviewRuleSet } from "./preview-repository";
import type { ArchiveRuleSetRequest, CreateRuleSetRequest, DuplicateRuleSetRequest, PublishRuleSetRequest, RuleSetListParams, RuleSetTransitionRequest, SetDefaultRuleSetRequest, UpdateRuleSetDraftRequest, ValidateRuleSetRequest } from "./types";

export function useRuleSetRepository() {
  const { runtimeMode, session } = useAdminSession(); const csrf = session?.csrf_token ?? ""; const preview = runtimeMode === "preview";
  return useMemo(() => ({
    isPreview: preview,
    list: (params: RuleSetListParams, signal?: AbortSignal) => preview ? listPreviewRuleSets(params) : listAdminRuleSets(params, signal),
    get: (id: string, signal?: AbortSignal) => preview ? getPreviewRuleSet(id) : getAdminRuleSet(id, signal),
    getOptions: (signal?: AbortSignal) => preview ? getPreviewRuleSetOptions() : getRuleSetOptions(signal),
    create: (request: CreateRuleSetRequest) => preview ? createPreviewRuleSet(request) : createAdminRuleSet(request, csrf),
    updateDraft: (id: string, request: UpdateRuleSetDraftRequest) => preview ? updatePreviewRuleSetDraft(id, request) : updateAdminRuleSetDraft(id, request, csrf),
    validate: (id: string, request: ValidateRuleSetRequest) => preview ? validatePreviewRuleSet(id, request) : validateAdminRuleSet(id, request, csrf),
    publish: (id: string, request: PublishRuleSetRequest) => preview ? publishPreviewRuleSet(id, request) : publishAdminRuleSet(id, request, csrf),
    archive: (id: string, request: ArchiveRuleSetRequest) => preview ? archivePreviewRuleSet(id, request) : archiveAdminRuleSet(id, request, csrf),
    restore: (id: string, request: RuleSetTransitionRequest) => preview ? restorePreviewRuleSet(id, request) : restoreAdminRuleSet(id, request, csrf),
    setDefault: (id: string, request: SetDefaultRuleSetRequest) => preview ? setDefaultPreviewRuleSet(id, request) : setDefaultAdminRuleSet(id, request, csrf),
    duplicate: (id: string, request: DuplicateRuleSetRequest) => preview ? duplicatePreviewRuleSet(id, request) : duplicateAdminRuleSet(id, request, csrf),
  }), [csrf, preview]);
}
