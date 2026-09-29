"use client";

import {
  AlertTriangle,
  Award,
  Building2,
  Check,
  Copy,
  DoorOpen,
  LoaderCircle,
  MailPlus,
  MapPinned,
  Plus,
  RefreshCw,
  UserRoundPlus,
  Wrench,
  X,
} from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import {
  CommitteeMembership,
  createCommitteeMembership,
  createDirectoryBlock,
  createDirectoryCommonArea,
  createDirectoryUnit,
  createMembershipInvitation,
  createTechnician,
  CurrentSociety,
  DirectoryBlock,
  DirectoryCommonArea,
  DirectoryUnit,
  getCurrentSociety,
  isFacilityManagerSession,
  listCommitteeMemberships,
  listDirectoryBlocks,
  listDirectoryCommonAreas,
  listDirectoryUnits,
  listMembershipInvitations,
  listTechnicians,
  MembershipInvitation,
  revokeMembershipInvitation,
  TechnicianProfile,
} from "@/lib/nivasops-api";
import { useWorkspaceSession } from "../../session-context";

const emptyBlockForm = { name: "", code: "" };
const emptyUnitForm = { block: "", door_number: "" };
const emptyCommonAreaForm = { name: "" };
const emptyTechnicianForm = { user_id: "", max_active_tickets: "5" };
const emptyCommitteeForm = {
  user_id: "",
  role: "MEMBER" as "PRESIDENT" | "SECRETARY" | "TREASURER" | "MEMBER",
};

const occupancyTypes = [
  { value: "OWNER", label: "Owner" },
  { value: "TENANT", label: "Tenant" },
  { value: "FAMILY", label: "Family member" },
] as const;
type OccupancyType = (typeof occupancyTypes)[number]["value"];

const staffRoles = [
  { value: "FACILITY_MANAGER", label: "Facility Manager" },
  { value: "HELPDESK", label: "Helpdesk Staff" },
  { value: "ESTATE_SUPERVISOR", label: "Estate Supervisor" },
] as const;
type StaffRole = (typeof staffRoles)[number]["value"];

const committeeRoles = [
  { value: "PRESIDENT", label: "President" },
  { value: "SECRETARY", label: "Secretary" },
  { value: "TREASURER", label: "Treasurer" },
  { value: "MEMBER", label: "Committee Member" },
] as const;
type CommitteeRole = (typeof committeeRoles)[number]["value"];

const emptyInvitationForm = {
  invitee_phone: "",
  invitee_email: "",
  persona: "RESIDENT" as "RESIDENT" | "STAFF" | "COMMITTEE",
  unit: "",
  occupancy_type: "OWNER" as OccupancyType,
  staff_role: "HELPDESK" as StaffRole,
  committee_role: "MEMBER" as CommitteeRole,
};

export default function SocietyDirectoryPage() {
  const { session } = useWorkspaceSession();
  const [society, setSociety] = useState<CurrentSociety | null>(null);
  const [blocks, setBlocks] = useState<DirectoryBlock[]>([]);
  const [units, setUnits] = useState<DirectoryUnit[]>([]);
  const [commonAreas, setCommonAreas] = useState<DirectoryCommonArea[]>([]);
  const [invitations, setInvitations] = useState<MembershipInvitation[]>([]);
  const [technicians, setTechnicians] = useState<TechnicianProfile[]>([]);
  const [committeeMembers, setCommitteeMembers] = useState<CommitteeMembership[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const [blockForm, setBlockForm] = useState(emptyBlockForm);
  const [unitForm, setUnitForm] = useState(emptyUnitForm);
  const [commonAreaForm, setCommonAreaForm] = useState(emptyCommonAreaForm);
  const [technicianForm, setTechnicianForm] = useState(emptyTechnicianForm);
  const [committeeForm, setCommitteeForm] = useState(emptyCommitteeForm);
  const [invitationForm, setInvitationForm] = useState(emptyInvitationForm);

  const [formError, setFormError] = useState("");
  const [technicianError, setTechnicianError] = useState("");
  const [committeeError, setCommitteeError] = useState("");
  const [invitationError, setInvitationError] = useState("");

  const [submitting, setSubmitting] = useState<"block" | "unit" | "area" | "technician" | "committee" | null>(null);
  const [creatingInvitation, setCreatingInvitation] = useState(false);
  const [revokingInvitationId, setRevokingInvitationId] = useState<string | null>(null);

  const [latestInvitationToken, setLatestInvitationToken] = useState<{
    email: string;
    token: string;
    link: string;
  } | null>(null);
  const [copiedTokenLink, setCopiedTokenLink] = useState(false);
  const [tokenLinkCopyError, setTokenLinkCopyError] = useState<string | null>(null);
  const [copiedUuid, setCopiedUuid] = useState<string | null>(null);
  const [uuidCopyError, setUuidCopyError] = useState<{ id: string; message: string } | null>(null);

  async function copyToClipboard(text: string, identifier: string) {
    setUuidCopyError(null);
    if (!navigator?.clipboard?.writeText) {
      setUuidCopyError({ id: identifier, message: "Clipboard not supported in this browser." });
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      setCopiedUuid(identifier);
      setTimeout(() => setCopiedUuid((current) => (current === identifier ? null : current)), 2500);
    } catch {
      setUuidCopyError({ id: identifier, message: "Unable to copy to clipboard." });
    }
  }

  async function copyActivationLink(link: string) {
    setTokenLinkCopyError(null);
    if (!navigator?.clipboard?.writeText) {
      setTokenLinkCopyError("Clipboard not supported in this browser. Please copy manually.");
      return;
    }
    try {
      await navigator.clipboard.writeText(link);
      setCopiedTokenLink(true);
      setTimeout(() => setCopiedTokenLink(false), 3000);
    } catch {
      setTokenLinkCopyError("Unable to copy activation link. Please copy manually.");
    }
  }

  async function loadDirectory() {
    if (!session) return;
    const [societyResult, blockResults, unitResults, commonAreaResults, invitationResults, techResults, committeeResults] = await Promise.all([
      getCurrentSociety(session),
      listDirectoryBlocks(session),
      listDirectoryUnits(session),
      listDirectoryCommonAreas(session),
      listMembershipInvitations(session),
      listTechnicians(session),
      listCommitteeMemberships(session),
    ]);
    setSociety(societyResult);
    setBlocks(blockResults);
    setUnits(unitResults);
    setCommonAreas(commonAreaResults);
    setInvitations(invitationResults);
    setTechnicians(techResults);
    setCommitteeMembers(committeeResults);
  }

  useEffect(() => {
    if (!session) return;
    let current = true;
    void Promise.all([
      getCurrentSociety(session),
      listDirectoryBlocks(session),
      listDirectoryUnits(session),
      listDirectoryCommonAreas(session),
      listMembershipInvitations(session),
      listTechnicians(session),
      listCommitteeMemberships(session),
    ])
      .then(([societyResult, blockResults, unitResults, commonAreaResults, invitationResults, techResults, committeeResults]) => {
        if (!current) return;
        setSociety(societyResult);
        setBlocks(blockResults);
        setUnits(unitResults);
        setCommonAreas(commonAreaResults);
        setInvitations(invitationResults);
        setTechnicians(techResults);
        setCommitteeMembers(committeeResults);
        setError("");
      })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof Error ? reason.message : "The society directory could not be loaded.");
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => { current = false; };
  }, [session]);

  async function refreshDirectory() {
    setRefreshing(true);
    setError("");
    try {
      await loadDirectory();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "The society directory could not be refreshed.");
    } finally {
      setRefreshing(false);
    }
  }

  async function submitBlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    setSubmitting("block");
    setFormError("");
    try {
      const block = await createDirectoryBlock(session, {
        name: blockForm.name.trim(),
        code: blockForm.code.trim(),
      });
      setBlocks((current) => [...current, block].sort((left, right) => left.code.localeCompare(right.code)));
      setUnitForm((current) => ({ ...current, block: block.id }));
      setBlockForm(emptyBlockForm);
    } catch (reason: unknown) {
      setFormError(reason instanceof Error ? reason.message : "The block could not be added.");
    } finally {
      setSubmitting(null);
    }
  }

  async function submitUnit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    setSubmitting("unit");
    setFormError("");
    try {
      const unit = await createDirectoryUnit(session, {
        block: unitForm.block,
        door_number: unitForm.door_number.trim(),
      });
      setUnits((current) => [...current, unit].sort((left, right) => left.door_number.localeCompare(right.door_number)));
      setUnitForm(emptyUnitForm);
    } catch (reason: unknown) {
      setFormError(reason instanceof Error ? reason.message : "The unit could not be added.");
    } finally {
      setSubmitting(null);
    }
  }

  async function submitCommonArea(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    setSubmitting("area");
    setFormError("");
    try {
      const commonArea = await createDirectoryCommonArea(session, { name: commonAreaForm.name.trim() });
      setCommonAreas((current) => [...current, commonArea].sort((left, right) => left.name.localeCompare(right.name)));
      setCommonAreaForm(emptyCommonAreaForm);
    } catch (reason: unknown) {
      setFormError(reason instanceof Error ? reason.message : "The common area could not be added.");
    } finally {
      setSubmitting(null);
    }
  }

  async function submitTechnician(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    const userId = technicianForm.user_id.trim();
    if (!userId) {
      setTechnicianError("Enter the User UUID for this in-house technician.");
      return;
    }
    const maxTickets = parseInt(technicianForm.max_active_tickets, 10);
    setSubmitting("technician");
    setTechnicianError("");
    try {
      const tech = await createTechnician(session, {
        user: userId,
        max_active_tickets: isNaN(maxTickets) ? 5 : maxTickets,
      });
      setTechnicians((current) => [...current, tech]);
      setTechnicianForm(emptyTechnicianForm);
    } catch (reason: unknown) {
      setTechnicianError(reason instanceof Error ? reason.message : "The technician profile could not be registered. Ensure the User UUID corresponds to an active member in this society.");
    } finally {
      setSubmitting(null);
    }
  }

  async function submitCommitteeMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    const userId = committeeForm.user_id.trim();
    if (!userId) {
      setCommitteeError("Enter the User UUID for this committee officer.");
      return;
    }
    setSubmitting("committee");
    setCommitteeError("");
    try {
      const member = await createCommitteeMembership(session, {
        user: userId,
        role: committeeForm.role,
      });
      setCommitteeMembers((current) => [...current, member]);
      setCommitteeForm(emptyCommitteeForm);
    } catch (reason: unknown) {
      setCommitteeError(reason instanceof Error ? reason.message : "The committee membership could not be registered. Ensure the User UUID corresponds to an active member in this society.");
    } finally {
      setSubmitting(null);
    }
  }

  async function submitInvitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    setCreatingInvitation(true);
    setInvitationError("");
    try {
      let invitationPayload;
      if (invitationForm.persona === "RESIDENT") {
        if (!invitationForm.unit) {
          setInvitationError("Select the unit for this resident invitation.");
          setCreatingInvitation(false);
          return;
        }
        invitationPayload = {
          invitee_phone: invitationForm.invitee_phone.trim(),
          invitee_email: invitationForm.invitee_email.trim(),
          persona: "RESIDENT" as const,
          unit: invitationForm.unit,
          occupancy_type: invitationForm.occupancy_type,
        };
      } else if (invitationForm.persona === "STAFF") {
        invitationPayload = {
          invitee_phone: invitationForm.invitee_phone.trim(),
          invitee_email: invitationForm.invitee_email.trim(),
          persona: "STAFF" as const,
          staff_role: invitationForm.staff_role,
        };
      } else {
        invitationPayload = {
          invitee_phone: invitationForm.invitee_phone.trim(),
          invitee_email: invitationForm.invitee_email.trim(),
          persona: "COMMITTEE" as const,
          committee_role: invitationForm.committee_role,
        };
      }

      const invitation = await createMembershipInvitation(session, invitationPayload);
      setInvitations((current) => [invitation, ...current]);
      setInvitationForm(emptyInvitationForm);

      if (invitation.invitation_token) {
        const origin = typeof window !== "undefined" ? window.location.origin : "";
        const link = `${origin}/activate?society_id=${encodeURIComponent(session.societyId)}&invitation_id=${encodeURIComponent(invitation.id)}&token=${encodeURIComponent(invitation.invitation_token)}`;
        setLatestInvitationToken({
          email: invitation.invitee_email,
          token: invitation.invitation_token,
          link,
        });
        setCopiedTokenLink(false);
        setTokenLinkCopyError(null);
      }
    } catch (reason: unknown) {
      setInvitationError(reason instanceof Error ? reason.message : "The invitation could not be issued.");
    } finally {
      setCreatingInvitation(false);
    }
  }

  async function revokeInvitation(invitationId: string) {
    if (!session) return;
    setRevokingInvitationId(invitationId);
    setInvitationError("");
    try {
      const invitation = await revokeMembershipInvitation(session, invitationId);
      setInvitations((current) => current.map((entry) => entry.id === invitation.id ? invitation : entry));
    } catch (reason: unknown) {
      setInvitationError(reason instanceof Error ? reason.message : "The invitation could not be revoked.");
    } finally {
      setRevokingInvitationId(null);
    }
  }

  if (!session || !isFacilityManagerSession(session)) {
    return <section className="empty-state error-state"><AlertTriangle size={25} /><h2>Society directory unavailable</h2><p>This workspace requires a Facility Manager session.</p></section>;
  }

  const activeBlocks = blocks.filter((block) => block.is_active);
  const activeUnits = units.filter((unit) => unit.is_active);
  const blockById = new Map(blocks.map((block) => [block.id, block]));

  return (
    <div className="operations-page location-directory-page page-enter">
      <section className="operations-header">
        <div>
          <p className="workspace-kicker">Society configuration</p>
          <h1>Locations, Staff, and Officers</h1>
          <p>Maintain locations for ticket submissions, staff/committee rosters, and multi-persona invitations.</p>
        </div>
        <button className="icon-command" type="button" title="Refresh location directory" aria-label="Refresh location directory" disabled={refreshing} onClick={() => void refreshDirectory()}>
          <RefreshCw className={refreshing ? "spin" : ""} size={17} />
        </button>
      </section>

      {loading ? <section className="location-directory-forms" aria-label="Loading society directory"><div className="location-directory-panel skeleton" /><div className="location-directory-panel skeleton" /><div className="location-directory-panel skeleton" /></section> : error ? (
        <section className="empty-state error-state"><AlertTriangle size={25} /><h2>Society directory unavailable</h2><p>{error}</p></section>
      ) : <>
        {society && <section className="society-context" aria-label="Society context">
          <span><strong>{society.registration_code}</strong> registration</span>
          <span><strong>{society.timezone}</strong> timezone</span>
          <span><strong>{society.locale}</strong> locale</span>
          <span><strong>{society.currency}</strong> currency</span>
          <span className={society.is_active ? "active" : "inactive"}>{society.is_active ? "Active society" : "Inactive society"}</span>
        </section>}
        <section className="location-directory-forms" aria-label="Location directory forms">
          <section className="location-directory-panel">
            <div className="location-directory-heading"><div><p className="workspace-kicker">Building</p><h2>Add block</h2></div><Building2 size={19} /></div>
            <form className="location-directory-form" onSubmit={submitBlock}>
              <label>Block name<input required maxLength={128} value={blockForm.name} onChange={(event) => setBlockForm((current) => ({ ...current, name: event.target.value }))} /></label>
              <label>Block code<input required maxLength={32} value={blockForm.code} onChange={(event) => setBlockForm((current) => ({ ...current, code: event.target.value }))} /></label>
              {formError && submitting === "block" && <p className="location-directory-error" role="alert">{formError}</p>}
              <button className="primary-command" type="submit" disabled={submitting !== null}>{submitting === "block" ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}{submitting === "block" ? "Adding block" : "Add block"}</button>
            </form>
          </section>

          <section className="location-directory-panel">
            <div className="location-directory-heading"><div><p className="workspace-kicker">Residence</p><h2>Add unit</h2></div><DoorOpen size={19} /></div>
            <form className="location-directory-form" onSubmit={submitUnit}>
              <label>Block<select required value={unitForm.block} onChange={(event) => setUnitForm((current) => ({ ...current, block: event.target.value }))}><option value="">Select an active block</option>{activeBlocks.map((block) => <option key={block.id} value={block.id}>{block.code} · {block.name}</option>)}</select></label>
              <label>Door number<input required maxLength={32} value={unitForm.door_number} onChange={(event) => setUnitForm((current) => ({ ...current, door_number: event.target.value }))} /></label>
              {activeBlocks.length === 0 && <p className="location-directory-note">Add an active block before recording a unit.</p>}
              {formError && submitting === "unit" && <p className="location-directory-error" role="alert">{formError}</p>}
              <button className="primary-command" type="submit" disabled={submitting !== null || activeBlocks.length === 0}>{submitting === "unit" ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}{submitting === "unit" ? "Adding unit" : "Add unit"}</button>
            </form>
          </section>

          <section className="location-directory-panel">
            <div className="location-directory-heading"><div><p className="workspace-kicker">Shared place</p><h2>Add common area</h2></div><MapPinned size={19} /></div>
            <form className="location-directory-form" onSubmit={submitCommonArea}>
              <label>Area name<input required maxLength={128} value={commonAreaForm.name} onChange={(event) => setCommonAreaForm((current) => ({ ...current, name: event.target.value }))} /></label>
              {formError && submitting === "area" && <p className="location-directory-error" role="alert">{formError}</p>}
              <button className="primary-command" type="submit" disabled={submitting !== null}>{submitting === "area" ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}{submitting === "area" ? "Adding area" : "Add common area"}</button>
            </form>
          </section>
        </section>

        <section className="location-directory-list" aria-labelledby="location-directory-list-title">
          <div className="location-directory-heading"><div><p className="workspace-kicker">Location inventory</p><h2 id="location-directory-list-title">Blocks, units, and common areas</h2></div><MapPinned size={19} /></div>
          <div className="location-directory-summary">
            <span><strong>{blocks.length}</strong> blocks</span><span><strong>{units.length}</strong> units</span><span><strong>{commonAreas.length}</strong> common areas</span>
          </div>
          <div className="location-directory-columns">
            <section><h3>Blocks</h3>{blocks.length === 0 ? <p className="quiet-copy">No blocks recorded.</p> : <div className="location-directory-rows">{blocks.map((block) => <div className="location-directory-row" key={block.id}><strong>{block.code}</strong><span>{block.name}</span><small>{block.is_active ? "Active" : "Inactive"}</small></div>)}</div>}</section>
            <section><h3>Units</h3>{units.length === 0 ? <p className="quiet-copy">No units recorded.</p> : <div className="location-directory-rows">{units.map((unit) => <div className="location-directory-row" key={unit.id}><strong>{blockById.get(unit.block)?.code ?? "Unknown block"}</strong><span>{unit.door_number}</span><small>{unit.is_active ? "Active" : "Inactive"}</small></div>)}</div>}</section>
            <section><h3>Common areas</h3>{commonAreas.length === 0 ? <p className="quiet-copy">No common areas recorded.</p> : <div className="location-directory-rows">{commonAreas.map((commonArea) => <div className="location-directory-row" key={commonArea.id}><strong>{commonArea.name}</strong><small>{commonArea.is_active ? "Active" : "Inactive"}</small></div>)}</div>}</section>
          </div>
        </section>

        <section className="membership-invitation-panel" aria-labelledby="committee-roster-title">
          <div className="location-directory-heading"><div><p className="workspace-kicker">Executive Governance</p><h2 id="committee-roster-title">Committee Officers Roster</h2></div><Award size={19} /></div>
          <div className="membership-invitation-grid">
            <form className="location-directory-form membership-invitation-form" onSubmit={submitCommitteeMember}>
              <p className="location-directory-note">Enroll an active society user into the executive management committee. (Enter their registered User UUID).</p>
              <label>User UUID<input required maxLength={64} placeholder="e.g. 11111111-2222-3333-4444-555555555555" value={committeeForm.user_id} onChange={(event) => setCommitteeForm((current) => ({ ...current, user_id: event.target.value }))} /></label>
              <label>Committee Role<select value={committeeForm.role} onChange={(event) => setCommitteeForm((current) => ({ ...current, role: event.target.value as CommitteeRole }))}>{committeeRoles.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}</select></label>
              {committeeError && <p className="location-directory-error" role="alert">{committeeError}</p>}
              <button className="primary-command" type="submit" disabled={submitting === "committee"}>
                {submitting === "committee" ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}
                {submitting === "committee" ? "Registering officer" : "Add committee officer"}
              </button>
            </form>

            <section className="membership-invitation-list" aria-label="Committee officers">
              {committeeMembers.length === 0 ? <p className="quiet-copy">No committee officers recorded.</p> : committeeMembers.map((member) => (
                <article className="membership-invitation-row" key={member.id}>
                  <div>
                    <strong>{member.role.replace("_", " ")} · {member.id.slice(0, 8)}</strong>
                    <span>User: <code>{member.user}</code></span>
                    <small>Started {new Date(member.starts_at).toLocaleDateString()}</small>
                  </div>
                  <div className="membership-invitation-actions">
                    <button
                      className="icon-command"
                      type="button"
                      title="Copy User UUID"
                      aria-label={`Copy User UUID ${member.user}`}
                      onClick={() => void copyToClipboard(member.user, `comm-${member.id}`)}
                    >
                      {copiedUuid === `comm-${member.id}` ? <Check size={14} /> : <Copy size={14} />}
                    </button>
                    <span className={`membership-invitation-status ${member.is_active ? "accepted" : "revoked"}`}>
                      {member.is_active ? "Active" : "Inactive"}
                    </span>
                  </div>
                  {uuidCopyError?.id === `comm-${member.id}` && (
                    <p className="location-directory-error" role="alert" style={{ fontSize: "0.75rem", marginTop: "0.25rem" }}>
                      {uuidCopyError.message}
                    </p>
                  )}
                </article>
              ))}
            </section>
          </div>
        </section>

        <section className="membership-invitation-panel" aria-labelledby="technicians-roster-title">
          <div className="location-directory-heading"><div><p className="workspace-kicker">Internal staff</p><h2 id="technicians-roster-title">In-house technician roster</h2></div><Wrench size={19} /></div>
          <div className="membership-invitation-grid">
            <form className="location-directory-form membership-invitation-form" onSubmit={submitTechnician}>
              <p className="location-directory-note">Enroll an active society user as an in-house technician with maximum concurrency capacity.</p>
              <label>User UUID<input required maxLength={64} placeholder="e.g. 11111111-2222-3333-4444-555555555555" value={technicianForm.user_id} onChange={(event) => setTechnicianForm((current) => ({ ...current, user_id: event.target.value }))} /></label>
              <label>Max active tickets concurrency<input required type="number" min={1} max={50} value={technicianForm.max_active_tickets} onChange={(event) => setTechnicianForm((current) => ({ ...current, max_active_tickets: event.target.value }))} /></label>
              {technicianError && <p className="location-directory-error" role="alert">{technicianError}</p>}
              <button className="primary-command" type="submit" disabled={submitting === "technician"}>
                {submitting === "technician" ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}
                {submitting === "technician" ? "Registering profile" : "Add in-house technician"}
              </button>
            </form>

            <section className="membership-invitation-list" aria-label="In-house technicians">
              {technicians.length === 0 ? <p className="quiet-copy">No in-house technicians recorded.</p> : technicians.map((tech) => (
                <article className="membership-invitation-row" key={tech.id}>
                  <div>
                    <strong>Technician · {tech.id.slice(0, 8)}</strong>
                    <span>User: <code>{tech.user}</code></span>
                    <small>Load: {tech.current_active_tickets_count} / {tech.max_active_tickets ?? "Unlimited"} active</small>
                  </div>
                  <div className="membership-invitation-actions">
                    <button
                      className="icon-command"
                      type="button"
                      title="Copy User UUID"
                      aria-label={`Copy User UUID ${tech.user}`}
                      onClick={() => void copyToClipboard(tech.user, `tech-${tech.id}`)}
                    >
                      {copiedUuid === `tech-${tech.id}` ? <Check size={14} /> : <Copy size={14} />}
                    </button>
                    <span className={`membership-invitation-status ${tech.is_active ? "accepted" : "revoked"}`}>
                      {tech.is_active ? "Active" : "Inactive"}
                    </span>
                  </div>
                  {uuidCopyError?.id === `tech-${tech.id}` && (
                    <p className="location-directory-error" role="alert" style={{ fontSize: "0.75rem", marginTop: "0.25rem" }}>
                      {uuidCopyError.message}
                    </p>
                  )}
                </article>
              ))}
            </section>
          </div>
        </section>

        <section className="membership-invitation-panel" aria-labelledby="membership-invitations-title">
          <div className="location-directory-heading"><div><p className="workspace-kicker">Multi-Persona Onboarding</p><h2 id="membership-invitations-title">Membership invitations</h2></div><MailPlus size={19} /></div>

          {latestInvitationToken && (
            <div className="auth-card-success" style={{ marginBottom: "1.5rem", position: "relative" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                <div>
                  <h4 style={{ margin: "0 0 0.5rem 0", color: "var(--brand-primary, #2563eb)" }}>One-Time Activation Link</h4>
                  <p style={{ margin: "0 0 0.5rem 0", fontSize: "0.875rem" }}>
                    A one-time activation link is available for <strong>{latestInvitationToken.email}</strong>. This link contains a sensitive activation token and should be communicated securely to the recipient:
                  </p>
                </div>
                <button
                  type="button"
                  className="icon-command"
                  onClick={() => {
                    setLatestInvitationToken(null);
                    setTokenLinkCopyError(null);
                    setCopiedTokenLink(false);
                  }}
                  title="Dismiss activation token"
                  aria-label="Dismiss activation token"
                >
                  <X size={15} />
                </button>
              </div>
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.5rem" }}>
                <input
                  readOnly
                  aria-label="One-time activation link"
                  value={latestInvitationToken.link}
                  style={{
                    flex: 1,
                    padding: "0.5rem 0.75rem",
                    background: "var(--surface, #ffffff)",
                    border: "1px solid var(--border, #cbd5e1)",
                    borderRadius: "6px",
                    fontSize: "0.8rem",
                    color: "var(--foreground, #0f172a)",
                  }}
                />
                <button
                  type="button"
                  className="primary-command"
                  style={{ padding: "0.5rem 0.75rem", fontSize: "0.8rem", whiteSpace: "nowrap" }}
                  onClick={() => void copyActivationLink(latestInvitationToken.link)}
                  aria-label="Copy activation link"
                >
                  {copiedTokenLink ? <Check size={14} /> : <Copy size={14} />}
                  {copiedTokenLink ? "Copied!" : "Copy Link"}
                </button>
              </div>
              {tokenLinkCopyError && (
                <p className="location-directory-error" role="alert" style={{ marginTop: "0.5rem", fontSize: "0.8rem" }}>
                  {tokenLinkCopyError}
                </p>
              )}
            </div>
          )}

          <div className="membership-invitation-grid">
            <form className="location-directory-form membership-invitation-form" onSubmit={submitInvitation}>
              <p className="location-directory-note">Issue a verified membership invitation. When the API response includes a one-time activation token, a secure link will be displayed above. Activation links are sensitive credentials and must be communicated securely to the invitee.</p>
              
              <label>Invitation Persona
                <select value={invitationForm.persona} onChange={(event) => setInvitationForm((current) => ({ ...current, persona: event.target.value as "RESIDENT" | "STAFF" | "COMMITTEE" }))}>
                  <option value="RESIDENT">Resident (Unit Occupant)</option>
                  <option value="STAFF">Internal Staff</option>
                  <option value="COMMITTEE">Committee Officer</option>
                </select>
              </label>

              <label>Email address<input required type="email" maxLength={254} value={invitationForm.invitee_email} onChange={(event) => setInvitationForm((current) => ({ ...current, invitee_email: event.target.value }))} placeholder="invitee@example.com" /></label>
              <label>Phone number<input required maxLength={32} value={invitationForm.invitee_phone} onChange={(event) => setInvitationForm((current) => ({ ...current, invitee_phone: event.target.value }))} placeholder="+919876543210" /></label>

              {invitationForm.persona === "RESIDENT" && (
                <>
                  <label>Unit<select required value={invitationForm.unit} onChange={(event) => setInvitationForm((current) => ({ ...current, unit: event.target.value }))}><option value="">Select an active unit</option>{activeUnits.map((unit) => <option key={unit.id} value={unit.id}>{blockById.get(unit.block)?.code ?? "Unknown block"} · {unit.door_number}</option>)}</select></label>
                  <label>Occupancy type<select value={invitationForm.occupancy_type} onChange={(event) => setInvitationForm((current) => ({ ...current, occupancy_type: event.target.value as OccupancyType }))}>{occupancyTypes.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}</select></label>
                  {activeUnits.length === 0 && <p className="location-directory-note">Add an active unit before inviting a resident.</p>}
                </>
              )}

              {invitationForm.persona === "STAFF" && (
                <label>Staff Role<select value={invitationForm.staff_role} onChange={(event) => setInvitationForm((current) => ({ ...current, staff_role: event.target.value as StaffRole }))}>{staffRoles.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}</select></label>
              )}

              {invitationForm.persona === "COMMITTEE" && (
                <label>Committee Role<select value={invitationForm.committee_role} onChange={(event) => setInvitationForm((current) => ({ ...current, committee_role: event.target.value as CommitteeRole }))}>{committeeRoles.map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}</select></label>
              )}

              {invitationError && <p className="location-directory-error" role="alert">{invitationError}</p>}
              <button className="primary-command" type="submit" disabled={creatingInvitation || revokingInvitationId !== null || (invitationForm.persona === "RESIDENT" && activeUnits.length === 0)}>
                {creatingInvitation ? <LoaderCircle className="spin" size={16} /> : <UserRoundPlus size={16} />}
                {creatingInvitation ? "Issuing invitation" : `Invite ${invitationForm.persona.toLowerCase()}`}
              </button>
            </form>

            <section className="membership-invitation-list" aria-label="Membership invitations">
              {invitations.length === 0 ? <p className="quiet-copy">No membership invitations have been issued.</p> : invitations.map((invitation) => {
                let detailsLabel = invitation.persona as string;
                if (invitation.persona === "RESIDENT" && invitation.unit) {
                  const unitObj = units.find((u) => u.id === invitation.unit);
                  const blockObj = unitObj ? blockById.get(unitObj.block) : null;
                  detailsLabel = `Resident · ${blockObj?.code ?? "Block"} ${unitObj?.door_number ?? ""} (${invitation.occupancy_type ?? "Occupant"})`;
                } else if (invitation.persona === "STAFF" && invitation.staff_role) {
                  detailsLabel = `Staff · ${invitation.staff_role.replace("_", " ")}`;
                } else if (invitation.persona === "COMMITTEE" && invitation.committee_role) {
                  detailsLabel = `Committee · ${invitation.committee_role.replace("_", " ")}`;
                }

                return (
                  <article className="membership-invitation-row" key={invitation.id}>
                    <div>
                      <strong>{invitation.invitee_email}</strong>
                      <span>{detailsLabel}</span>
                      <small>Expires {new Date(invitation.expires_at).toLocaleString()}</small>
                    </div>
                    <div className="membership-invitation-actions">
                      <span className={`membership-invitation-status ${invitation.status.toLowerCase()}`}>{invitation.status}</span>
                      {invitation.status === "PENDING" && (
                        <button
                          className="membership-invitation-revoke"
                          type="button"
                          title={`Revoke invitation for ${invitation.invitee_email}`}
                          aria-label={`Revoke invitation for ${invitation.invitee_email}`}
                          disabled={creatingInvitation || revokingInvitationId !== null}
                          onClick={() => void revokeInvitation(invitation.id)}
                        >
                          {revokingInvitationId === invitation.id ? <LoaderCircle className="spin" size={15} /> : <X size={15} />}
                        </button>
                      )}
                    </div>
                  </article>
                );
              })}
            </section>
          </div>
        </section>
      </>}
    </div>
  );
}