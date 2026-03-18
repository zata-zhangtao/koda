/** 邮件通知设置模态框
 *
 * 提供 SMTP 配置和接收地址的表单，支持保存和发送测试邮件
 */

import { useEffect, useState } from "react";
import { emailSettingsApi } from "../api/client";
import type { EmailSettingsUpdate } from "../types";

interface EmailSettingsModalProps {
  onClose: () => void;
}

const DEFAULT_FORM_STATE: EmailSettingsUpdate = {
  smtp_host: "",
  smtp_port: 465,
  smtp_username: "",
  smtp_password: "",
  smtp_use_ssl: true,
  receiver_email: "",
  is_enabled: true,
};

export function EmailSettingsModal({ onClose }: EmailSettingsModalProps) {
  const [formState, setFormState] = useState<EmailSettingsUpdate>(DEFAULT_FORM_STATE);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ text: string; isError: boolean } | null>(null);

  useEffect(() => {
    emailSettingsApi
      .get()
      .then((existingSettings) => {
        setFormState({
          smtp_host: existingSettings.smtp_host,
          smtp_port: existingSettings.smtp_port,
          smtp_username: existingSettings.smtp_username,
          smtp_password: "", // 不回显真实密码，提示用户重新输入
          smtp_use_ssl: existingSettings.smtp_use_ssl,
          receiver_email: existingSettings.receiver_email,
          is_enabled: existingSettings.is_enabled,
        });
      })
      .catch(() => {
        // 尚未配置，使用默认值
      })
      .finally(() => setIsLoading(false));
  }, []);

  const handleSave = async () => {
    if (!formState.smtp_host || !formState.smtp_username || !formState.receiver_email) {
      setStatusMessage({ text: "Please fill in SMTP host, username, and receiver email.", isError: true });
      return;
    }

    setIsSaving(true);
    setStatusMessage(null);
    try {
      await emailSettingsApi.save(formState);
      setStatusMessage({ text: "Settings saved successfully.", isError: false });
    } catch (saveError) {
      setStatusMessage({
        text: saveError instanceof Error ? saveError.message : "Failed to save settings.",
        isError: true,
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleTest = async () => {
    setIsTesting(true);
    setStatusMessage(null);
    try {
      const testResult = await emailSettingsApi.test("Koda Test Email", "If you received this, your SMTP config is working!");
      setStatusMessage({ text: testResult.message, isError: false });
    } catch (testError) {
      setStatusMessage({
        text: testError instanceof Error ? testError.message : "Test failed.",
        isError: true,
      });
    } finally {
      setIsTesting(false);
    }
  };

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div style={styles.header}>
          <h2 style={styles.title}>📧 Email Notification Settings</h2>
          <button style={styles.closeButton} onClick={onClose}>✕</button>
        </div>

        {isLoading ? (
          <div style={styles.loadingText}>Loading...</div>
        ) : (
          <div style={styles.form}>
            {/* Enable toggle */}
            <div style={styles.toggleRow}>
              <label style={styles.toggleLabel}>Enable email notifications</label>
              <input
                type="checkbox"
                checked={formState.is_enabled}
                onChange={(e) => setFormState((prev) => ({ ...prev, is_enabled: e.target.checked }))}
                style={styles.checkbox}
              />
            </div>

            <div style={styles.divider} />

            {/* SMTP Host + Port */}
            <div style={styles.row}>
              <div style={{ ...styles.field, flex: 2 }}>
                <label style={styles.label}>SMTP Host</label>
                <input
                  style={styles.input}
                  type="text"
                  placeholder="smtp.gmail.com"
                  value={formState.smtp_host}
                  onChange={(e) => setFormState((prev) => ({ ...prev, smtp_host: e.target.value }))}
                />
              </div>
              <div style={{ ...styles.field, flex: 1 }}>
                <label style={styles.label}>Port</label>
                <input
                  style={styles.input}
                  type="number"
                  placeholder="465"
                  value={formState.smtp_port}
                  onChange={(e) =>
                    setFormState((prev) => ({ ...prev, smtp_port: parseInt(e.target.value, 10) || 465 }))
                  }
                />
              </div>
            </div>

            {/* SSL toggle */}
            <div style={styles.toggleRow}>
              <label style={styles.toggleLabel}>Use SSL (port 465). Uncheck for STARTTLS (port 587).</label>
              <input
                type="checkbox"
                checked={formState.smtp_use_ssl}
                onChange={(e) => setFormState((prev) => ({ ...prev, smtp_use_ssl: e.target.checked }))}
                style={styles.checkbox}
              />
            </div>

            {/* SMTP Username */}
            <div style={styles.field}>
              <label style={styles.label}>SMTP Username (sender email)</label>
              <input
                style={styles.input}
                type="email"
                placeholder="you@example.com"
                value={formState.smtp_username}
                onChange={(e) => setFormState((prev) => ({ ...prev, smtp_username: e.target.value }))}
              />
            </div>

            {/* SMTP Password */}
            <div style={styles.field}>
              <label style={styles.label}>SMTP Password / App Password</label>
              <input
                style={styles.input}
                type="password"
                placeholder="Enter password (leave blank to keep existing)"
                value={formState.smtp_password}
                onChange={(e) => setFormState((prev) => ({ ...prev, smtp_password: e.target.value }))}
              />
            </div>

            {/* Receiver Email */}
            <div style={styles.field}>
              <label style={styles.label}>Receive notifications at</label>
              <input
                style={styles.input}
                type="email"
                placeholder="notify@example.com"
                value={formState.receiver_email}
                onChange={(e) => setFormState((prev) => ({ ...prev, receiver_email: e.target.value }))}
              />
            </div>

            {/* Status message */}
            {statusMessage && (
              <div
                style={{
                  ...styles.statusMessage,
                  ...(statusMessage.isError ? styles.statusError : styles.statusSuccess),
                }}
              >
                {statusMessage.text}
              </div>
            )}

            {/* Action buttons */}
            <div style={styles.actions}>
              <button
                style={{ ...styles.button, ...styles.testButton }}
                onClick={handleTest}
                disabled={isTesting || isSaving}
              >
                {isTesting ? "Sending..." : "Send Test Email"}
              </button>
              <button
                style={{ ...styles.button, ...styles.saveButton }}
                onClick={handleSave}
                disabled={isSaving || isTesting}
              >
                {isSaving ? "Saving..." : "Save Settings"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  overlay: {
    position: "fixed",
    inset: 0,
    backgroundColor: "rgba(0,0,0,0.5)",
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
    width: "480px",
    maxWidth: "90vw",
    maxHeight: "85vh",
    overflowY: "auto",
    boxShadow: "0 20px 60px rgba(0,0,0,0.6)",
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: "20px",
  },
  title: {
    margin: 0,
    fontSize: "16px",
    fontWeight: 600,
    color: "#cdd6f4",
  },
  closeButton: {
    background: "none",
    border: "none",
    color: "#6c7086",
    fontSize: "16px",
    cursor: "pointer",
    padding: "4px 8px",
    borderRadius: "4px",
  },
  loadingText: {
    color: "#6c7086",
    textAlign: "center",
    padding: "20px",
  },
  form: {
    display: "flex",
    flexDirection: "column",
    gap: "14px",
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
  },
  divider: {
    height: "1px",
    backgroundColor: "#313244",
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
  statusMessage: {
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
    marginTop: "4px",
  },
  button: {
    padding: "8px 16px",
    borderRadius: "6px",
    border: "none",
    cursor: "pointer",
    fontSize: "13px",
    fontWeight: 500,
  },
  testButton: {
    backgroundColor: "#313244",
    color: "#cdd6f4",
  },
  saveButton: {
    backgroundColor: "#89b4fa",
    color: "#1e1e2e",
  },
};
