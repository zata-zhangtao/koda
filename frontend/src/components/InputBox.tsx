/** 超级输入框组件
 *
 * 支持 Markdown 输入、命令识别和图片粘贴
 */

import { useRef, useState } from "react";
import { DevLogStateTag, type Task } from "../types";
import { mediaApi } from "../api/client";

interface InputBoxProps {
  onSubmit: (text: string) => void;
  activeTask: Task | null;
}

const STATE_BUTTONS = [
  { tag: DevLogStateTag.BUG, icon: "🐛", label: "Bug", shortcut: "/bug" },
  { tag: DevLogStateTag.FIXED, icon: "✅", label: "Fix", shortcut: "/fix" },
  { tag: DevLogStateTag.OPTIMIZATION, icon: "💡", label: "Opt", shortcut: "/opt" },
  { tag: DevLogStateTag.TRANSFERRED, icon: "⏭️", label: "Transfer", shortcut: "/transfer" },
];

export function InputBox({ onSubmit, activeTask }: InputBoxProps) {
  const [inputText, setInputText] = useState("");
  const [isUploading, setIsUploading] = useState(false);
  const [pastedImage, setPastedImage] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = async () => {
    if (!inputText.trim() && !pastedImage) return;

    // 如果有粘贴的图片，先上传
    if (pastedImage) {
      setIsUploading(true);
      try {
        await mediaApi.uploadImage(pastedImage, inputText.trim());
        setInputText("");
        setPastedImage(null);
        setImagePreview(null);
      } catch (error) {
        console.error("Failed to upload image:", error);
        alert("Failed to upload image");
      } finally {
        setIsUploading(false);
      }
    } else {
      // 纯文本提交
      onSubmit(inputText.trim());
      setInputText("");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handlePaste = async (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items;

    for (const item of Array.from(items)) {
      if (item.type.startsWith("image/")) {
        e.preventDefault();
        const file = item.getAsFile();
        if (file) {
          setPastedImage(file);
          // 创建预览
          const reader = new FileReader();
          reader.onload = (event) => {
            setImagePreview(event.target?.result as string);
          };
          reader.readAsDataURL(file);
        }
        break;
      }
    }
  };

  const handleStateButtonClick = (shortcut: string) => {
    const currentText = inputText;
    // 检查是否已经有命令前缀
    const commandRegex = /^\/[a-z]+\s*/;
    const newText = commandRegex.test(currentText)
      ? currentText.replace(commandRegex, `${shortcut} `)
      : `${shortcut} ${currentText}`;
    setInputText(newText);
    textareaRef.current?.focus();
  };

  const removePastedImage = () => {
    setPastedImage(null);
    setImagePreview(null);
  };

  return (
    <div style={styles.container}>
      {/* 图片预览 */}
      {imagePreview && (
        <div style={styles.previewContainer}>
          <img src={imagePreview} alt="Preview" style={styles.previewImage} />
          <button style={styles.removeImageBtn} onClick={removePastedImage}>
            ×
          </button>
        </div>
      )}

      {/* 输入框 */}
      <textarea
        ref={textareaRef}
        value={inputText}
        onChange={(e) => setInputText(e.target.value)}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        placeholder={
          activeTask
            ? `Type your log... (Shift+Enter for new line, Ctrl+V to paste image)\nCommands: /bug, /fix, /opt, /transfer, /task <title>`
            : "Create a task first to start logging..."
        }
        style={styles.textarea}
        disabled={!activeTask || isUploading}
      />

      {/* 底部工具栏 */}
      <div style={styles.toolbar}>
        {/* 状态快捷按钮 */}
        <div style={styles.stateButtons}>
          {STATE_BUTTONS.map((btn) => (
            <button
              key={btn.tag}
              style={styles.stateButton}
              onClick={() => handleStateButtonClick(btn.shortcut)}
              disabled={!activeTask || isUploading}
              title={`${btn.label} (${btn.shortcut})`}
            >
              <span>{btn.icon}</span>
              <span style={styles.buttonLabel}>{btn.label}</span>
            </button>
          ))}
        </div>

        {/* 提交按钮 */}
        <button
          style={{
            ...styles.submitButton,
            opacity: !inputText.trim() && !pastedImage ? 0.5 : 1,
          }}
          onClick={handleSubmit}
          disabled={(!inputText.trim() && !pastedImage) || !activeTask || isUploading}
        >
          {isUploading ? "Uploading..." : "Enter to Submit"}
        </button>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: "16px 20px",
    backgroundColor: "#16213e",
    borderTop: "1px solid #2d3748",
  },
  previewContainer: {
    position: "relative",
    display: "inline-block",
    marginBottom: "12px",
  },
  previewImage: {
    maxWidth: "200px",
    maxHeight: "150px",
    borderRadius: "6px",
    border: "1px solid #2d3748",
  },
  removeImageBtn: {
    position: "absolute",
    top: "-8px",
    right: "-8px",
    width: "20px",
    height: "20px",
    borderRadius: "50%",
    backgroundColor: "#f56565",
    color: "white",
    border: "none",
    cursor: "pointer",
    fontSize: "14px",
    lineHeight: "1",
  },
  textarea: {
    width: "100%",
    minHeight: "80px",
    maxHeight: "200px",
    padding: "12px",
    backgroundColor: "#1a1a2e",
    border: "1px solid #2d3748",
    borderRadius: "8px",
    color: "#eaeaea",
    fontSize: "14px",
    lineHeight: "1.6",
    resize: "vertical",
    fontFamily: "inherit",
  },
  toolbar: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: "12px",
  },
  stateButtons: {
    display: "flex",
    gap: "8px",
  },
  stateButton: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
    padding: "6px 12px",
    backgroundColor: "#1a1a2e",
    border: "1px solid #2d3748",
    borderRadius: "6px",
    color: "#a0a0a0",
    cursor: "pointer",
    fontSize: "13px",
  },
  buttonLabel: {
    fontSize: "12px",
  },
  submitButton: {
    padding: "8px 20px",
    backgroundColor: "#e94560",
    color: "white",
    border: "none",
    borderRadius: "6px",
    cursor: "pointer",
    fontSize: "14px",
    fontWeight: 500,
  },
};
