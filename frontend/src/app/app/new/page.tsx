"use client";

import {
  ArrowLeft,
  ArrowRight,
  Building2,
  Check,
  FileImage,
  FileText,
  Home,
  LoaderCircle,
  MapPin,
  Paperclip,
  Save,
  ShieldAlert,
  Wrench,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import {
  createTicket,
  getTicketOptions,
  issueAttachmentUploadSlot,
  completeAttachmentUpload,
  uploadAttachmentFile,
  validateAttachmentFile,
  TicketCategory,
  TicketOptions,
  TicketWorkflow,
} from "@/lib/nivasops-api";
import { useWorkspaceSession } from "../session-context";

type LocationKind = "unit" | "common_area" | "none";

export default function NewRequestPage() {
  const router = useRouter();
  const { session } = useWorkspaceSession();
  const [options, setOptions] = useState<TicketOptions | null>(null);
  const [optionsError, setOptionsError] = useState("");
  const [workflow, setWorkflow] = useState<TicketWorkflow>("SERVICE");
  const [categoryId, setCategoryId] = useState("");
  const [subcategoryId, setSubcategoryId] = useState("");
  const [locationKind, setLocationKind] = useState<LocationKind>("unit");
  const [locationId, setLocationId] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [stagedFiles, setStagedFiles] = useState<File[]>([]);
  const [attachmentError, setAttachmentError] = useState("");

  useEffect(() => {
    if (!session) return;
    let current = true;
    getTicketOptions(session)
      .then((result) => {
        if (current) setOptions(result);
      })
      .catch((reason: unknown) => {
        if (current) setOptionsError(reason instanceof Error ? reason.message : "Request options could not be loaded.");
      });
    return () => { current = false; };
  }, [session]);

  const categories = options?.categories.filter((category) => category.workflow_type === workflow) ?? [];
  const selectedCategory = categories.find((category) => category.id === categoryId);
  const selectedSubcategory = selectedCategory?.subcategories.find((subcategory) => subcategory.id === subcategoryId);
  const availableLocations = locationKind === "unit" ? options?.units ?? [] : options?.common_areas ?? [];
  const requiresLocation = workflow === "SERVICE" || selectedCategory?.allows_no_location === false;
  const locationIsValid = locationKind === "none" ? !requiresLocation : Boolean(locationId);
  const canSave = Boolean(session && selectedCategory && selectedSubcategory && title.trim() && description.trim() && locationIsValid);

  function chooseWorkflow(nextWorkflow: TicketWorkflow) {
    setWorkflow(nextWorkflow);
    setCategoryId("");
    setSubcategoryId("");
    setLocationKind(nextWorkflow === "SERVICE" ? "unit" : "none");
    setLocationId("");
    setSubmitError("");
  }

  function chooseCategory(category: TicketCategory) {
    setCategoryId(category.id);
    setSubcategoryId("");
    if (category.allows_unit_location && options?.units.length) {
      setLocationKind("unit");
      setLocationId(options.units[0].id);
    } else if (category.allows_common_area_location && options?.common_areas.length) {
      setLocationKind("common_area");
      setLocationId(options.common_areas[0].id);
    } else {
      setLocationKind("none");
      setLocationId("");
    }
  }

  function chooseLocation(kind: LocationKind) {
    setLocationKind(kind);
    if (kind === "unit") setLocationId(options?.units[0]?.id ?? "");
    if (kind === "common_area") setLocationId(options?.common_areas[0]?.id ?? "");
    if (kind === "none") setLocationId("");
  }

  function handleFileSelect(event: React.ChangeEvent<HTMLInputElement>) {
    if (!event.target.files) return;
    const files = Array.from(event.target.files);
    setAttachmentError("");
    for (const file of files) {
      const error = validateAttachmentFile(file);
      if (error) {
        setAttachmentError(error);
        return;
      }
    }
    setStagedFiles((prev) => [...prev, ...files]);
    event.target.value = "";
  }

  function removeStagedFile(index: number) {
    setStagedFiles((prev) => prev.filter((_, i) => i !== index));
  }

  function formatBytes(bytes: number) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || !canSave) return;
    setSaving(true);
    setSubmitError("");
    try {
      const ticket = await createTicket(session, {
        workflow,
        category: categoryId,
        subcategory: subcategoryId,
        ...(locationKind === "unit" ? { unit: locationId } : {}),
        ...(locationKind === "common_area" ? { common_area: locationId } : {}),
        title: title.trim(),
        description: description.trim(),
      });

      let currentVersion = ticket.state_version;
      for (const file of stagedFiles) {
        try {
          const slot = await issueAttachmentUploadSlot(session, workflow, ticket.id, {
            expected_version: currentVersion,
            filename: file.name,
            content_type: file.type || "image/jpeg",
            byte_size: file.size,
          });
          await uploadAttachmentFile(slot, file);
          await completeAttachmentUpload(session, slot.attachment.id, workflow, ticket.id).catch(() => {});
          currentVersion = slot.state_version ?? (currentVersion + 1);
        } catch (uploadErr) {
          console.error("Failed to upload staged attachment", uploadErr);
        }
      }

      router.push(`/app/tickets/${workflow.toLowerCase()}/${ticket.id}`);
    } catch (reason) {
      setSubmitError(reason instanceof Error ? reason.message : "The draft could not be saved.");
      setSaving(false);
    }
  }

  return (
    <div className="request-studio page-enter">
      <div className="page-titlebar">
        <Link className="icon-command" href="/app" aria-label="Back to home" title="Back to home"><ArrowLeft size={18} /></Link>
        <div><p className="workspace-kicker">RES-02 · New request</p><h1>Describe what needs attention</h1><p>Save a draft, review it, then submit it to society operations.</p></div>
      </div>

      <ol className="studio-progress" aria-label="Request creation progress">
        <li className="active"><span>1</span><p><strong>Request type</strong><small>Choose the workflow</small></p></li>
        <li className={categoryId ? "active" : ""}><span>2</span><p><strong>Classify</strong><small>Category and location</small></p></li>
        <li className={title && description ? "active" : ""}><span>3</span><p><strong>Details</strong><small>Explain the issue</small></p></li>
      </ol>

      {optionsError ? (
        <div className="empty-state error-state"><ShieldAlert size={26} /><h3>Creation options unavailable</h3><p>{optionsError}</p></div>
      ) : !options ? (
        <div className="studio-loading"><LoaderCircle size={22} /><span>Loading society request options</span></div>
      ) : (
        <form onSubmit={handleSave}>
          <section className="studio-section">
            <div className="studio-section-title"><span>01</span><div><h2>Where does this belong?</h2><p>Service work and society matters follow different operational paths.</p></div></div>
            <div className="workflow-selector">
              <button className={workflow === "SERVICE" ? "selected" : ""} type="button" onClick={() => chooseWorkflow("SERVICE")}>
                <span className="workflow-icon"><Wrench size={24} /></span><span><strong>Inside my home</strong><small>Repairs and services for your registered unit</small></span>{workflow === "SERVICE" && <Check size={18} />}
              </button>
              <button className={workflow === "GOVERNANCE" ? "selected" : ""} type="button" onClick={() => chooseWorkflow("GOVERNANCE")}>
                <span className="workflow-icon amber"><Building2 size={24} /></span><span><strong>Society or civic matter</strong><small>Common facilities, conduct, security, or governance</small></span>{workflow === "GOVERNANCE" && <Check size={18} />}
              </button>
            </div>
          </section>

          <section className="studio-section">
            <div className="studio-section-title"><span>02</span><div><h2>Classify the request</h2><p>Selection determines routing and default priority.</p></div></div>
            {categories.length ? (
              <div className="category-grid">
                {categories.map((category) => (
                  <button className={categoryId === category.id ? "selected" : ""} type="button" key={category.id} onClick={() => chooseCategory(category)}>
                    <span>{category.name.slice(0, 2).toUpperCase()}</span><strong>{category.name}</strong><small>{category.subcategories.length} options</small>
                  </button>
                ))}
              </div>
            ) : <p className="inline-notice">No active categories are configured for this workflow.</p>}

            {selectedCategory && (
              <div className="field-cluster reveal-section">
                <label>Specific issue
                  <select required value={subcategoryId} onChange={(event) => setSubcategoryId(event.target.value)}>
                    <option value="">Select a subcategory</option>
                    {selectedCategory.subcategories.map((subcategory) => <option key={subcategory.id} value={subcategory.id}>{subcategory.name} · {subcategory.default_priority}</option>)}
                  </select>
                </label>
                <div>
                  <span className="field-label">Location</span>
                  <div className="location-switcher">
                    {selectedCategory.allows_unit_location && options.units.length > 0 && <button className={locationKind === "unit" ? "selected" : ""} type="button" onClick={() => chooseLocation("unit")}><Home size={16} /> My unit</button>}
                    {selectedCategory.allows_common_area_location && options.common_areas.length > 0 && <button className={locationKind === "common_area" ? "selected" : ""} type="button" onClick={() => chooseLocation("common_area")}><Building2 size={16} /> Common area</button>}
                    {selectedCategory.allows_no_location && workflow === "GOVERNANCE" && <button className={locationKind === "none" ? "selected" : ""} type="button" onClick={() => chooseLocation("none")}><MapPin size={16} /> Society-wide</button>}
                  </div>
                  {locationKind !== "none" && (
                    <select aria-label="Request location" required value={locationId} onChange={(event) => setLocationId(event.target.value)}>
                      {availableLocations.map((location) => <option key={location.id} value={location.id}>{"door_number" in location ? `${location.block} · ${location.door_number}` : location.name}</option>)}
                    </select>
                  )}
                </div>
                {selectedSubcategory && <div className={`priority-preview priority-preview-${selectedSubcategory.default_priority.toLowerCase()}`}><span>{selectedSubcategory.default_priority}</span><p><strong>Default priority</strong><small>Confirmed by society policy when the request is processed.</small></p></div>}
              </div>
            )}
          </section>

          <section className="studio-section">
            <div className="studio-section-title"><span>03</span><div><h2>Add clear details</h2><p>Precise descriptions help the operations team triage quickly.</p></div></div>
            <div className="details-grid">
              <div className="form-stack">
                <label>Issue title<input required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Example: Main water valve leaking" /></label>
                <label>Description<textarea required rows={7} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Describe the exact location, severity, and anything already attempted." /></label>
              </div>
              <div className="attachment-upload-box">
                <div className="attachment-upload-header">
                  <div className="attachment-icon-pill">
                    <FileImage size={20} />
                  </div>
                  <div>
                    <h3>Photos and documents</h3>
                    <p>Add photos (PNG, JPEG, WebP) or documents (PDF) up to 20MB.</p>
                  </div>
                </div>

                <div className="attachment-picker-row">
                  <label className="attachment-picker-btn">
                    <Paperclip size={15} />
                    <span>Attach files</span>
                    <input
                      type="file"
                      multiple
                      accept="image/jpeg,image/png,image/webp,application/pdf"
                      onChange={handleFileSelect}
                      style={{ display: "none" }}
                    />
                  </label>
                  <small className="attachment-hint">Max 20MB per file · Quarantined and verified</small>
                </div>

                {attachmentError && (
                  <p className="form-error attachment-form-error">{attachmentError}</p>
                )}

                {stagedFiles.length > 0 && (
                  <ul className="staged-attachments-list">
                    {stagedFiles.map((file, idx) => (
                      <li key={`${file.name}-${idx}`} className="staged-attachment-item">
                        <div className="staged-file-meta">
                          {file.type === "application/pdf" ? (
                            <FileText size={16} className="file-icon-pdf" />
                          ) : (
                            <FileImage size={16} className="file-icon-img" />
                          )}
                          <span className="staged-filename" title={file.name}>
                            {file.name}
                          </span>
                          <span className="staged-filesize">
                            {formatBytes(file.size)}
                          </span>
                        </div>
                        <button
                          type="button"
                          className="staged-remove-btn"
                          aria-label={`Remove ${file.name}`}
                          onClick={() => removeStagedFile(idx)}
                        >
                          <X size={14} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          </section>

          <footer className="studio-footer">
            <div><ShieldAlert size={18} /><p><strong>Review before submission</strong><small>This step saves a draft. You can submit it from the request detail screen.</small></p></div>
            {submitError && <p className="form-error">{submitError}</p>}
            <button className="primary-command" type="submit" disabled={!canSave || saving}>{saving ? <LoaderCircle className="spin" size={18} /> : <Save size={18} />}{saving ? "Saving draft" : "Save request draft"}<ArrowRight size={17} /></button>
          </footer>
        </form>
      )}
    </div>
  );
}