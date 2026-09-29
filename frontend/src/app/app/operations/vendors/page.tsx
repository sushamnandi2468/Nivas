"use client";

import {
  AlertTriangle,
  Building2,
  Check,
  ClipboardList,
  Copy,
  HardHat,
  LoaderCircle,
  Plus,
  RefreshCw,
  UsersRound,
} from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";

import {
  createVendor,
  createVendorContract,
  createVendorStaffMembership,
  isFacilityManagerSession,
  listVendorContracts,
  listVendors,
  listVendorStaffMemberships,
  Vendor,
  VendorContract,
  VendorStaffMembership,
} from "@/lib/nivasops-api";
import { useWorkspaceSession } from "../../session-context";

const emptyVendorForm = {
  company_name: "",
  contact_person: "",
  phone_number: "",
  email: "",
};

const emptyContractForm = {
  vendor: "",
  starts_on: "",
  ends_on: "",
  max_active_tickets: "",
};

const emptyStaffForm = {
  vendor: "",
  contract: "",
  user: "",
  role: "WORKER" as "DISPATCHER" | "WORKER",
};

function contractStatus(contract: VendorContract, today: string) {
  if (!contract.is_active) return "Inactive";
  if (contract.starts_on > today) return "Scheduled";
  if (contract.ends_on < today) return "Expired";
  return "Active";
}

function capacityLabel(contract: VendorContract) {
  return contract.max_active_tickets === null
    ? "Unlimited capacity"
    : `${contract.current_active_tickets_count} of ${contract.max_active_tickets} active`;
}

export default function VendorDirectoryPage() {
  const { session } = useWorkspaceSession();
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [contracts, setContracts] = useState<VendorContract[]>([]);
  const [staffMembers, setStaffMembers] = useState<VendorStaffMembership[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");

  const [vendorForm, setVendorForm] = useState(emptyVendorForm);
  const [vendorError, setVendorError] = useState("");
  const [creatingVendor, setCreatingVendor] = useState(false);

  const [contractForm, setContractForm] = useState(emptyContractForm);
  const [contractError, setContractError] = useState("");
  const [creatingContract, setCreatingContract] = useState(false);

  const [staffForm, setStaffForm] = useState(emptyStaffForm);
  const [staffError, setStaffError] = useState("");
  const [creatingStaff, setCreatingStaff] = useState(false);
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

  async function loadDirectory() {
    if (!session) return;
    const [vendorResults, contractResults, staffResults] = await Promise.all([
      listVendors(session),
      listVendorContracts(session),
      listVendorStaffMemberships(session),
    ]);
    setVendors(vendorResults);
    setContracts(contractResults);
    setStaffMembers(staffResults);
  }

  useEffect(() => {
    if (!session) return;
    let current = true;
    void Promise.all([
      listVendors(session),
      listVendorContracts(session),
      listVendorStaffMemberships(session),
    ])
      .then(([vendorResults, contractResults, staffResults]) => {
        if (!current) return;
        setVendors(vendorResults);
        setContracts(contractResults);
        setStaffMembers(staffResults);
        setError("");
      })
      .catch((reason: unknown) => {
        if (current) setError(reason instanceof Error ? reason.message : "Vendor records could not be loaded.");
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
      setError(reason instanceof Error ? reason.message : "Vendor records could not be refreshed.");
    } finally {
      setRefreshing(false);
    }
  }

  async function submitVendor(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    setCreatingVendor(true);
    setVendorError("");
    try {
      const vendor = await createVendor(session, {
        company_name: vendorForm.company_name.trim(),
        contact_person: vendorForm.contact_person.trim(),
        phone_number: vendorForm.phone_number.trim(),
        email: vendorForm.email.trim(),
      });
      setVendors((current) => [...current, vendor].sort((left, right) => left.company_name.localeCompare(right.company_name)));
      setContractForm((current) => ({ ...current, vendor: vendor.id }));
      setVendorForm(emptyVendorForm);
    } catch (reason: unknown) {
      setVendorError(reason instanceof Error ? reason.message : "The vendor could not be added.");
    } finally {
      setCreatingVendor(false);
    }
  }

  async function submitContract(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    const rawCapacity = contractForm.max_active_tickets.trim();
    const capacity = rawCapacity ? Number(rawCapacity) : null;
    if (!contractForm.vendor || !contractForm.starts_on || !contractForm.ends_on) {
      setContractError("Select a vendor and provide both contract dates.");
      return;
    }
    if (contractForm.ends_on < contractForm.starts_on) {
      setContractError("End date cannot be earlier than the start date.");
      return;
    }
    if (rawCapacity && (capacity === null || !Number.isSafeInteger(capacity) || capacity <= 0)) {
      setContractError("Capacity must be a whole number greater than zero, or left blank for unlimited capacity.");
      return;
    }

    setCreatingContract(true);
    setContractError("");
    try {
      const contract = await createVendorContract(session, {
        vendor: contractForm.vendor,
        starts_on: contractForm.starts_on,
        ends_on: contractForm.ends_on,
        max_active_tickets: capacity,
      });
      setContracts((current) => [...current, contract].sort((left, right) => right.starts_on.localeCompare(left.starts_on)));
      setContractForm(emptyContractForm);
    } catch (reason: unknown) {
      setContractError(reason instanceof Error ? reason.message : "The contract could not be added.");
    } finally {
      setCreatingContract(false);
    }
  }

  async function submitStaff(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) return;
    const userId = staffForm.user.trim();
    if (!staffForm.vendor || !staffForm.contract || !userId) {
      setStaffError("Select vendor, contract, and enter the user UUID.");
      return;
    }
    setCreatingStaff(true);
    setStaffError("");
    try {
      const member = await createVendorStaffMembership(session, {
        vendor: staffForm.vendor,
        contract: staffForm.contract,
        user: userId,
        role: staffForm.role,
      });
      setStaffMembers((current) => [...current, member]);
      setStaffForm(emptyStaffForm);
    } catch (reason: unknown) {
      setStaffError(reason instanceof Error ? reason.message : "Vendor staff could not be registered. Ensure the User UUID corresponds to an active member in this society.");
    } finally {
      setCreatingStaff(false);
    }
  }

  if (!session || !isFacilityManagerSession(session)) {
    return <section className="empty-state error-state"><AlertTriangle size={25} /><h2>Vendor administration unavailable</h2><p>This workspace requires a Facility Manager session.</p></section>;
  }

  const today = new Date().toISOString().slice(0, 10);
  const vendorById = new Map(vendors.map((vendor) => [vendor.id, vendor]));
  const contractById = new Map(contracts.map((contract) => [contract.id, contract]));
  const activeVendors = vendors.filter((vendor) => vendor.is_active);
  const eligibleContractsForStaff = contracts.filter((c) => c.vendor === staffForm.vendor && c.is_active);

  return (
    <div className="operations-page vendor-directory-page page-enter">
      <section className="operations-header">
        <div>
          <p className="workspace-kicker">Configuration</p>
          <h1>Vendors, Contracts, and Field Staff</h1>
          <p>Maintain active provider records, service contracts, dispatchers, and field technician workers.</p>
        </div>
        <button className="icon-command" type="button" title="Refresh vendors and contracts" aria-label="Refresh vendors and contracts" disabled={refreshing} onClick={() => void refreshDirectory()}>
          <RefreshCw className={refreshing ? "spin" : ""} size={17} />
        </button>
      </section>

      {loading ? <section className="vendor-directory-grid" aria-label="Loading vendor directory"><div className="vendor-directory-panel skeleton" /><div className="vendor-directory-panel skeleton" /></section> : error ? (
        <section className="empty-state error-state"><AlertTriangle size={25} /><h2>Vendor directory unavailable</h2><p>{error}</p></section>
      ) : <>
        <section className="vendor-directory-grid" aria-label="Vendor administration forms">
          <section className="vendor-directory-panel">
            <div className="vendor-directory-heading"><div><p className="workspace-kicker">Provider record</p><h2>Add vendor</h2></div><Building2 size={19} /></div>
            <form className="vendor-directory-form" onSubmit={submitVendor}>
              <label>Company name<input required maxLength={255} value={vendorForm.company_name} onChange={(event) => setVendorForm((current) => ({ ...current, company_name: event.target.value }))} /></label>
              <label>Contact person<input required maxLength={255} value={vendorForm.contact_person} onChange={(event) => setVendorForm((current) => ({ ...current, contact_person: event.target.value }))} /></label>
              <label>Phone number<input required maxLength={32} value={vendorForm.phone_number} onChange={(event) => setVendorForm((current) => ({ ...current, phone_number: event.target.value }))} /></label>
              <label>Email<input type="email" maxLength={254} value={vendorForm.email} onChange={(event) => setVendorForm((current) => ({ ...current, email: event.target.value }))} /></label>
              {vendorError && <p className="vendor-directory-error" role="alert">{vendorError}</p>}
              <button className="primary-command" type="submit" disabled={creatingVendor}>{creatingVendor ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}{creatingVendor ? "Adding vendor" : "Add vendor"}</button>
            </form>
          </section>

          <section className="vendor-directory-panel">
            <div className="vendor-directory-heading"><div><p className="workspace-kicker">Dispatch capacity</p><h2>Add contract</h2></div><ClipboardList size={19} /></div>
            <form className="vendor-directory-form" onSubmit={submitContract}>
              <label>Vendor<select required value={contractForm.vendor} onChange={(event) => setContractForm((current) => ({ ...current, vendor: event.target.value }))}><option value="">Select an active vendor</option>{activeVendors.map((vendor) => <option key={vendor.id} value={vendor.id}>{vendor.company_name}</option>)}</select></label>
              <div className="vendor-date-grid"><label>Starts on<input required type="date" value={contractForm.starts_on} onChange={(event) => setContractForm((current) => ({ ...current, starts_on: event.target.value }))} /></label><label>Ends on<input required type="date" value={contractForm.ends_on} onChange={(event) => setContractForm((current) => ({ ...current, ends_on: event.target.value }))} /></label></div>
              <label>Maximum active tickets<input inputMode="numeric" min="1" placeholder="Leave blank for unlimited" type="number" value={contractForm.max_active_tickets} onChange={(event) => setContractForm((current) => ({ ...current, max_active_tickets: event.target.value }))} /></label>
              {activeVendors.length === 0 && <p className="vendor-directory-note">Add an active vendor before recording a contract.</p>}
              {contractError && <p className="vendor-directory-error" role="alert">{contractError}</p>}
              <button className="primary-command" type="submit" disabled={creatingContract || activeVendors.length === 0}>{creatingContract ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}{creatingContract ? "Adding contract" : "Add contract"}</button>
            </form>
          </section>

          <section className="vendor-directory-panel">
            <div className="vendor-directory-heading"><div><p className="workspace-kicker">Contract staff</p><h2>Enroll vendor staff</h2></div><HardHat size={19} /></div>
            <form className="vendor-directory-form" onSubmit={submitStaff}>
              <p className="vendor-directory-note">Enroll a registered society user as a vendor dispatcher or on-ground worker bound to a contract.</p>
              <label>Vendor<select required value={staffForm.vendor} onChange={(event) => setStaffForm((current) => ({ ...current, vendor: event.target.value, contract: "" }))}><option value="">Select vendor</option>{activeVendors.map((vendor) => <option key={vendor.id} value={vendor.id}>{vendor.company_name}</option>)}</select></label>
              <label>Contract<select required value={staffForm.contract} onChange={(event) => setStaffForm((current) => ({ ...current, contract: event.target.value }))} disabled={!staffForm.vendor}><option value="">Select contract</option>{eligibleContractsForStaff.map((c) => <option key={c.id} value={c.id}>{c.starts_on} to {c.ends_on} ({capacityLabel(c)})</option>)}</select></label>
              <label>User UUID<input required maxLength={64} placeholder="e.g. 11111111-2222-3333-4444-555555555555" value={staffForm.user} onChange={(event) => setStaffForm((current) => ({ ...current, user: event.target.value }))} /></label>
              <label>Staff Role<select value={staffForm.role} onChange={(event) => setStaffForm((current) => ({ ...current, role: event.target.value as "DISPATCHER" | "WORKER" }))}><option value="WORKER">On-Ground Field Worker</option><option value="DISPATCHER">Vendor Dispatcher</option></select></label>
              {staffError && <p className="vendor-directory-error" role="alert">{staffError}</p>}
              <button className="primary-command" type="submit" disabled={creatingStaff || !staffForm.contract}>
                {creatingStaff ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}
                {creatingStaff ? "Enrolling staff" : "Enroll vendor staff"}
              </button>
            </form>
          </section>
        </section>

        <section className="vendor-directory-list" aria-labelledby="vendor-directory-list-title">
          <div className="vendor-directory-heading"><div><p className="workspace-kicker">Directory</p><h2 id="vendor-directory-list-title">Current vendors and contracts</h2></div><UsersRound size={19} /></div>
          {vendors.length === 0 ? <p className="quiet-copy">No vendors have been recorded for this society.</p> : <div className="vendor-directory-rows" role="list">{vendors.map((vendor) => {
            const vendorContracts = contracts.filter((contract) => contract.vendor === vendor.id);
            return <article className="vendor-directory-row" key={vendor.id} role="listitem">
              <div className="vendor-directory-company"><Building2 size={18} /><div><strong>{vendor.company_name}</strong><span>{vendor.contact_person} · {vendor.phone_number}</span>{vendor.email && <small>{vendor.email}</small>}</div></div>
              <div className="vendor-contract-summary">{vendorContracts.length === 0 ? <span>No contracts recorded</span> : vendorContracts.map((contract) => <div key={contract.id}><span className={`vendor-contract-status ${contractStatus(contract, today).toLowerCase()}`}>{contractStatus(contract, today)}</span><strong>{capacityLabel(contract)}</strong><small>{contract.starts_on} to {contract.ends_on}</small></div>)}</div>
            </article>;
          })}</div>}
          {contracts.some((contract) => !vendorById.has(contract.vendor)) && <p className="vendor-directory-error" role="alert">A contract refers to a vendor record that is not available in this directory response.</p>}
        </section>

        <section className="membership-invitation-panel" aria-labelledby="vendor-staff-title" style={{ marginTop: "1.5rem" }}>
          <div className="location-directory-heading"><div><p className="workspace-kicker">Field Operations</p><h2 id="vendor-staff-title">Vendor Staff & Field Workers</h2></div><HardHat size={19} /></div>
          <div className="membership-invitation-list" aria-label="Vendor staff memberships">
            {staffMembers.length === 0 ? <p className="quiet-copy">No vendor staff members enrolled.</p> : staffMembers.map((member) => {
              const vendorObj = vendorById.get(member.vendor);
              const contractObj = contractById.get(member.contract);
              return (
                <article className="membership-invitation-row" key={member.id}>
                  <div>
                    <strong>{member.role === "DISPATCHER" ? "Dispatcher" : "Field Worker"} · {vendorObj?.company_name ?? "Vendor"}</strong>
                    <span>User: <code>{member.user}</code> · Contract: {contractObj ? `${contractObj.starts_on} to ${contractObj.ends_on}` : member.contract.slice(0, 8)}</span>
                    <small>Enrolled {new Date(member.starts_at).toLocaleDateString()}</small>
                  </div>
                  <div className="membership-invitation-actions">
                    <button
                      className="icon-command"
                      type="button"
                      title="Copy User UUID"
                      aria-label={`Copy User UUID ${member.user}`}
                      onClick={() => void copyToClipboard(member.user, `vstaff-${member.id}`)}
                    >
                      {copiedUuid === `vstaff-${member.id}` ? <Check size={14} /> : <Copy size={14} />}
                    </button>
                    <span className={`membership-invitation-status ${member.is_active ? "accepted" : "revoked"}`}>
                      {member.is_active ? "Active" : "Inactive"}
                    </span>
                  </div>
                  {uuidCopyError?.id === `vstaff-${member.id}` && (
                    <p className="vendor-directory-error" role="alert" style={{ fontSize: "0.75rem", marginTop: "0.25rem" }}>
                      {uuidCopyError.message}
                    </p>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      </>}
    </div>
  );
}
