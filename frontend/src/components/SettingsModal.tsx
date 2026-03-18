/** 统一设置模态框
 *
 * 通过 Tab 页聚合所有设置项（邮件通知、WebDAV 同步等），
 * 方便后续扩展更多设置类别.
 */

import { useEffect, useState } from "react";
import { emailSettingsApi, webdavSettingsApi } from "../api/client";
import type { EmailSettingsUpdate, WebDAVSettingsUpdate } from "../types";

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

type SettingsTab = "email" | "webdav";

interface StatusMessage {
  text: string;
  isError: boolean;
}

interface SettingsModalProps {
  onClose: () => void;
}

// ─────────────────────────────────────────────
// Default form states
// ─────────────────────────────────────────────

const DEFAULT_EMAIL_FORM: EmailSettingsUpdate = {
  smtp_host: "",
  smtp_port: 465,
  smtp_username: "",
  smtp_password: "",
  smtp_use_ssl: true,
  receiver_email: "",
  is_enabled: true,
};

const DEFAULT_WEBDAV_FORM: WebDAVSettingsUpdate = {
  server_url: "",
  username: "",
  password: "",
  remote_path: "/koda-backup/",
  is_enabled: true,
};

// ─────────────────────────────────────────────
// Root modal
// ─────────────────────────────────────────────

export function SettingsModal({ onClose }: SettingsModalProps) {
  const [activeTab, setActiveTab] = useState<SettingsTab>("email");

  return (
    <div style={s.overlay} onClick={onClose}>
      <div style={s.modal} onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div style={s.header}>
          <h2 style={s.title}>⚙️ Settings</h2>
          <button style={s.closeBtn} onClick={onClose}>✕</button>
        </div>

        {/* Tabs */}
        <div style={s.tabBar}>
          {(
            [
              ["email", "📧 Email"],
              ["webdav", "☁️ WebDAV Sync"],
            ] as const
          ).map(([tabId, tabLabel]) => (
            <button
              key={tabId}
              style={{ ...s.tabBtn, ...(activeTab === tabId ? s.tabBtnActive : {}) }}
              onClick={() => setActiveTab(tabId)}
            >
              {tabLabel}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div style={s.tabContent}>
          {activeTab === "email" && <EmailTab />}
          {activeTab === "webdav" && <WebDAVTab />}
        </div>

      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Email tab
// ─────────────────────────────────────────────

function EmailTab() {
  const [formState, setFormState] = useState<EmailSettingsUpdate>(DEFAULT_EMAIL_FORM);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [status, setStatus] = useState<StatusMessage | null>(null);

  useEffect(() => {
    emailSettingsApi
      .get()
      .then((existingSettings) => {
        setFormState({
          smtp_host: existingSettings.smtp_host,
          smtp_port: existingSettings.smtp_port,
          smtp_username: existingSettings.smtp_username,
          smtp_password: "",
          smtp_use_ssl: existingSettings.smtp_use_ssl,
          receiver_email: existingSettings.receiver_email,
          is_enabled: existingSettings.is_enabled,
        });
      })
      .catch(() => { /* not yet configured — keep defaults */ })
      .finally(() => setIsLoading(false));
  }, []);

  const handleSave = async () => {
    if (!formState.smtp_host || !formState.smtp_username || !formState.receiver_email) {
      setStatus({ text: "Please fill in SMTP host, username, and receiver email.", isError: true });
      return;
    }
    setIsSaving(true);
    setStatus(null);
    try {
      await emailSettingsApi.save(formState);
      setStatus({ text: "Settings saved.", isError: false });
    } catch (err) {
      setStatus({ text: err instanceof Error ? err.message : "Failed to save.", isError: true });
    } finally {
      setIsSaving(false);
    }
  };

  const handleTest = async () => {
    setIsTesting(true);
    setStatus(null);
    try {
      const result = await emailSettingsApi.test(
        "Koda Test Email",
        "If you received this, your SMTP config is working!"
      );
      setStatus({ text: result.message, isError: false });
    } catch (err) {
      setStatus({ text: err instanceof Error ? err.message : "Test failed.", isError: true });
    } finally {
      setIsTesting(false);
    }
  };

  if (isLoading) return <div style={s.loadingText}>Loading...</div>;

  return (
    <div style={s.form}>
      <ToggleRow
        label="Enable email notifications"
        checked={formState.is_enabled}
        onChange={(v) => setFormState((p) => ({ ...p, is_enabled: v }))}
      />
      <Divider />

      <div style={s.row}>
        <Field label="SMTP Host" style={{ flex: 2 }}>
          <input style={s.input} type="text" placeholder="smtp.gmail.com"
            value={formState.smtp_host}
            onChange={(e) => setFormState((p) => ({ ...p, smtp_host: e.target.value }))} />
        </Field>
        <Field label="Port" style={{ flex: 1 }}>
          <input style={s.input} type="number" placeholder="465"
            value={formState.smtp_port}
            onChange={(e) => setFormState((p) => ({ ...p, smtp_port: parseInt(e.target.value, 10) || 465 }))} />
        </Field>
      </div>

      <ToggleRow
        label="Use SSL (port 465). Uncheck for STARTTLS (port 587)."
        checked={formState.smtp_use_ssl}
        onChange={(v) => setFormState((p) => ({ ...p, smtp_use_ssl: v }))}
      />

      <Field label="SMTP Username (sender email)">
        <input style={s.input} type="email" placeholder="you@example.com"
          value={formState.smtp_username}
          onChange={(e) => setFormState((p) => ({ ...p, smtp_username: e.target.value }))} />
      </Field>

      <Field label="SMTP Password / App Password">
        <input style={s.input} type="password" placeholder="Leave blank to keep existing"
          value={formState.smtp_password}
          onChange={(e) => setFormState((p) => ({ ...p, smtp_password: e.target.value }))} />
      </Field>

      <Field label="Receive notifications at">
        <input style={s.input} type="email" placeholder="notify@example.com"
          value={formState.receiver_email}
          onChange={(e) => setFormState((p) => ({ ...p, receiver_email: e.target.value }))} />
      </Field>

      <StatusBanner status={status} />

      <div style={s.actions}>
        <button style={{ ...s.btn, ...s.secondaryBtn }}
          onClick={handleTest} disabled={isTesting || isSaving}>
          {isTesting ? "Sending..." : "Send Test Email"}
        </button>
        <button style={{ ...s.btn, ...s.primaryBtn }}
          onClick={handleSave} disabled={isSaving || isTesting}>
          {isSaving ? "Saving..." : "Save"}
        </button>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// WebDAV tab
// ─────────────────────────────────────────────

function WebDAVTab() {
  const [formState, setFormState] = useState<WebDAVSettingsUpdate>(DEFAULT_WEBDAV_FORM);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);
  const [status, setStatus] = useState<StatusMessage | null>(null);

  useEffect(() => {
    webdavSettingsApi
      .get()
      .then((existingSettings) => {
        setFormState({
          server_url: existingSettings.server_url,
          username: existingSettings.username,
          password: "",
          remote_path: existingSettings.remote_path,
          is_enabled: existingSettings.is_enabled,
        });
      })
      .catch(() => { /* not yet configured */ })
      .finally(() => setIsLoading(false));
  }, []);

  const handleSave = async () => {
    if (!formState.server_url || !formState.username) {
      setStatus({ text: "Please fill in server URL and username.", isError: true });
      return;
    }
    setIsSaving(true);
    setStatus(null);
    try {
      await webdavSettingsApi.save(formState);
      setStatus({ text: "Settings saved.", isError: false });
    } catch (err) {
      setStatus({ text: err instanceof Error ? err.message : "Failed to save.", isError: true });
    } finally {
      setIsSaving(false);
    }
  };

  const handleTest = async () => {
    setIsTesting(true);
    setStatus(null);
    try {
      const result = await webdavSettingsApi.test();
      setStatus({ text: result.message, isError: !result.success });
    } catch (err) {
      setStatus({ text: err instanceof Error ? err.message : "Test failed.", isError: true });
    } finally {
      setIsTesting(false);
    }
  };

  const handleUpload = async () => {
    setIsUploading(true);
    setStatus(null);
    try {
      const result = await webdavSettingsApi.upload();
      setStatus({ text: result.message, isError: false });
    } catch (err) {
      setStatus({ text: err instanceof Error ? err.message : "Upload failed.", isError: true });
    } finally {
      setIsUploading(false);
    }
  };

  const handleDownload = async () => {
    const confirmed = confirm(
      "⚠️ This will overwrite your local database with the remote backup. Are you sure?"
    );
    if (!confirmed) return;
    setIsDownloading(true);
    setStatus(null);
    try {
      const result = await webdavSettingsApi.download();
      setStatus({ text: result.message + " — Please restart the app to reload data.", isError: false });
    } catch (err) {
      setStatus({ text: err instanceof Error ? err.message : "Download failed.", isError: true });
    } finally {
      setIsDownloading(false);
    }
  };

  const isBusy = isSaving || isTesting || isUploading || isDownloading;

  if (isLoading) return <div style={s.loadingText}>Loading...</div>;

  return (
    <div style={s.form}>
      <ToggleRow
        label="Enable WebDAV sync"
        checked={formState.is_enabled}
        onChange={(v) => setFormState((p) => ({ ...p, is_enabled: v }))}
      />
      <Divider />

      <Field label="WebDAV Server URL">
        <input style={s.input} type="url"
          placeholder="https://dav.example.com/remote.php/dav/files/user/"
          value={formState.server_url}
          onChange={(e) => setFormState((p) => ({ ...p, server_url: e.target.value }))} />
      </Field>

      <div style={s.row}>
        <Field label="Username" style={{ flex: 1 }}>
          <input style={s.input} type="text" placeholder="your-username"
            value={formState.username}
            onChange={(e) => setFormState((p) => ({ ...p, username: e.target.value }))} />
        </Field>
        <Field label="Password" style={{ flex: 1 }}>
          <input style={s.input} type="password" placeholder="Leave blank to keep existing"
            value={formState.password}
            onChange={(e) => setFormState((p) => ({ ...p, password: e.target.value }))} />
        </Field>
      </div>

      <Field label="Remote path (directory on server)">
        <input style={s.input} type="text" placeholder="/koda-backup/"
          value={formState.remote_path}
          onChange={(e) => setFormState((p) => ({ ...p, remote_path: e.target.value }))} />
      </Field>

      <StatusBanner status={status} />

      {/* Save + Test */}
      <div style={s.actions}>
        <button style={{ ...s.btn, ...s.secondaryBtn }}
          onClick={handleTest} disabled={isBusy}>
          {isTesting ? "Testing..." : "Test Connection"}
        </button>
        <button style={{ ...s.btn, ...s.primaryBtn }}
          onClick={handleSave} disabled={isBusy}>
          {isSaving ? "Saving..." : "Save"}
        </button>
      </div>

      {/* Sync actions */}
      <Divider />
      <div style={s.syncLabel}>Manual Sync</div>
      <div style={s.actions}>
        <button style={{ ...s.btn, ...s.secondaryBtn }}
          onClick={handleUpload} disabled={isBusy}>
          {isUploading ? "Uploading..." : "⬆ Upload DB to WebDAV"}
        </button>
        <button style={{ ...s.btn, ...s.dangerBtn }}
          onClick={handleDownload} disabled={isBusy}>
          {isDownloading ? "Downloading..." : "⬇ Restore DB from WebDAV"}
        </button>
      </div>
      <div style={s.hint}>
        Uploads/restores the local SQLite database file. Restore will overwrite local data.
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Shared sub-components
// ─────────────────────────────────────────────

function ToggleRow({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div style={s.toggleRow}>
      <span style={s.toggleLabel}>{label}</span>
      <input type="checkbox" checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        style={s.checkbox} />
    </div>
  );
}

function Divider() {
  return <div style={s.divider} />;
}

function Field({
  label,
  children,
  style,
}: {
  label: string;
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div style={{ ...s.field, ...style }}>
      <label style={s.label}>{label}</label>
      {children}
    </div>
  );
}

function StatusBanner({ status }: { status: StatusMessage | null }) {
  if (!status) return null;
  return (
    <div style={{ ...s.statusMsg, ...(status.isError ? s.statusError : s.statusSuccess) }}>
      {status.text}
    </div>
  );
}

// ─────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────

const s: Record<string, React.CSSProperties> = {
  overlay: {
    position: "fixed",
    inset: 0,
    backgroundColor: "rgba(0,0,0,0.55)",
    zIndex: 1000,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
  },
  modal: {
    backgroundColor: "#1e1e2e",
    border: "1px solid #313244",
    borderRadius: "12px",
    padding: "24px",
    width: "520px",
    maxWidth: "92vw",
    maxHeight: "88vh",
    overflowY: "auto",
    boxShadow: "0 20px 60px rgba(0,0,0,0.6)",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "16px",
  },
  title: {
    margin: 0,
    fontSize: "16px",
    fontWeight: 600,
    color: "#cdd6f4",
  },
  closeBtn: {
    background: "none",
    border: "none",
    color: "#6c7086",
    fontSize: "16px",
    cursor: "pointer",
    padding: "4px 8px",
    borderRadius: "4px",
  },
  tabBar: {
    display: "flex",
    gap: "4px",
    marginBottom: "20px",
    borderBottom: "1px solid #313244",
    paddingBottom: "0",
  },
  tabBtn: {
    background: "none",
    border: "none",
    borderBottom: "2px solid transparent",
    marginBottom: "-1px",
    padding: "8px 14px",
    fontSize: "13px",
    color: "#6c7086",
    cursor: "pointer",
    borderRadius: "4px 4px 0 0",
  },
  tabBtnActive: {
    color: "#89b4fa",
    borderBottomColor: "#89b4fa",
  },
  tabContent: {},
  form: {
    display: "flex",
    flexDirection: "column",
    gap: "14px",
  },
  loadingText: {
    color: "#6c7086",
    textAlign: "center",
    padding: "20px",
  },
  toggleRow: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  toggleLabel: {
    color: "#cdd6f4",
    fontSize: "13px",
  },
  checkbox: {
    width: "16px",
    height: "16px",
    cursor: "pointer",
    flexShrink: 0,
  },
  divider: {
    height: "1px",
    backgroundColor: "#313244",
  },
  syncLabel: {
    fontSize: "11px",
    color: "#6c7086",
    textTransform: "uppercase",
    letterSpacing: "0.5px",
  },
  row: {
    display: "flex",
    gap: "12px",
  },
  field: {
    display: "flex",
    flexDirection: "column",
    gap: "6px",
  },
  label: {
    color: "#a6adc8",
    fontSize: "12px",
  },
  input: {
    backgroundColor: "#181825",
    border: "1px solid #313244",
    borderRadius: "6px",
    padding: "8px 10px",
    color: "#cdd6f4",
    fontSize: "13px",
    outline: "none",
    width: "100%",
    boxSizing: "border-box",
  },
  statusMsg: {
    padding: "10px 14px",
    borderRadius: "6px",
    fontSize: "13px",
  },
  statusError: {
    backgroundColor: "rgba(243,139,168,0.15)",
    border: "1px solid rgba(243,139,168,0.4)",
    color: "#f38ba8",
  },
  statusSuccess: {
    backgroundColor: "rgba(166,227,161,0.15)",
    border: "1px solid rgba(166,227,161,0.4)",
    color: "#a6e3a1",
  },
  actions: {
    display: "flex",
    gap: "10px",
    justifyContent: "flex-end",
  },
  btn: {
    padding: "8px 16px",
    borderRadius: "6px",
    border: "none",
    cursor: "pointer",
    fontSize: "13px",
    fontWeight: 500,
  },
  primaryBtn: {
    backgroundColor: "#89b4fa",
    color: "#1e1e2e",
  },
  secondaryBtn: {
    backgroundColor: "#313244",
    color: "#cdd6f4",
  },
  dangerBtn: {
    backgroundColor: "rgba(243,139,168,0.2)",
    color: "#f38ba8",
    border: "1px solid rgba(243,139,168,0.3)",
  },
  hint: {
    fontSize: "11px",
    color: "#6c7086",
    lineHeight: "1.4",
  },
};
