/** 日志卡片组件
 *
 * 显示单条日志的内容、状态、图片和时间戳
 */

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { DevLogStateTag, type DevLog } from "../types";
import { formatMonthDayTime } from "../utils/datetime";

interface LogCardProps {
  log: DevLog;
}

const STATE_CONFIG: Record<
  DevLogStateTag,
  { icon: string; color: string; borderColor: string }
> = {
  [DevLogStateTag.NONE]: { icon: "", color: "#eaeaea", borderColor: "transparent" },
  [DevLogStateTag.BUG]: { icon: "🐛", color: "#f56565", borderColor: "#f56565" },
  [DevLogStateTag.OPTIMIZATION]: {
    icon: "💡",
    color: "#ed8936",
    borderColor: "#ed8936",
  },
  [DevLogStateTag.FIXED]: { icon: "✅", color: "#48bb78", borderColor: "#48bb78" },
  [DevLogStateTag.TRANSFERRED]: {
    icon: "⏭️",
    color: "#4299e1",
    borderColor: "#4299e1",
  },
};

export function LogCard({ log }: LogCardProps) {
  const stateConfig = STATE_CONFIG[log.state_tag];
  const formattedTime = formatMonthDayTime(log.created_at);
  const thumbnailSrc = mapMediaPathToPublicUrl(log.media_thumbnail_path);
  const originalImageSrc = mapMediaPathToPublicUrl(log.media_original_image_path);

  return (
    <div
      style={{
        ...styles.container,
        borderLeftColor: stateConfig.borderColor,
      }}
    >
      {/* 头部信息 */}
      <div style={styles.header}>
        <div style={styles.meta}>
          {log.state_tag !== DevLogStateTag.NONE && (
            <span style={{ ...styles.stateBadge, color: stateConfig.color }}>
              {stateConfig.icon} {log.state_tag}
            </span>
          )}
          <span style={styles.taskName}>{log.task_title}</span>
          <span style={styles.timestamp}>{formattedTime}</span>
        </div>
      </div>

      {/* 文本内容 */}
      {log.text_content && (
        <div style={styles.content}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {log.text_content}
          </ReactMarkdown>
        </div>
      )}

      {/* 图片 */}
      {thumbnailSrc && (
        <div style={styles.imageContainer}>
          <img
            src={thumbnailSrc}
            alt="Screenshot"
            style={styles.thumbnail}
            onClick={() => {
              if (originalImageSrc) {
                window.open(originalImageSrc, "_blank");
              }
            }}
          />
          {/* AI 状态指示器 (Phase 2) */}
          {log.ai_processing_status && (
            <div style={styles.aiStatus}>
              {getAIStatusIcon(log.ai_processing_status)}
            </div>
          )}
        </div>
      )}

      {/* AI 分析结果 (Phase 2, 已确认时显示) */}
      {log.ai_processing_status === "CONFIRMED" && log.ai_generated_title && (
        <div style={styles.aiResult}>
          <div style={styles.aiTitle}>🤖 {log.ai_generated_title}</div>
          {log.ai_analysis_text && (
            <div style={styles.aiAnalysis}>{log.ai_analysis_text}</div>
          )}
          {log.ai_extracted_code && (
            <pre style={styles.aiCode}>
              <code>{log.ai_extracted_code}</code>
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function mapMediaPathToPublicUrl(rawMediaPath: string | null): string | null {
  if (!rawMediaPath) {
    return null;
  }

  const normalizedMediaPath = rawMediaPath.replace(/\\/g, "/").replace(/^\/+/, "");
  if (normalizedMediaPath.startsWith("data/media/")) {
    return `/${normalizedMediaPath.slice("data".length).replace(/^\/+/, "")}`;
  }

  if (normalizedMediaPath.startsWith("media/")) {
    return `/${normalizedMediaPath}`;
  }

  return `/${normalizedMediaPath}`;
}

function getAIStatusIcon(status: string): string {
  switch (status) {
    case "PENDING":
      return "⏳";
    case "PROCESSING":
      return "🔄";
    case "WAITING_REVIEW":
      return "🔔";
    case "CONFIRMED":
      return "✓";
    default:
      return "";
  }
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    backgroundColor: "#16213e",
    borderRadius: "8px",
    padding: "16px",
    borderLeftWidth: "3px",
    borderLeftStyle: "solid",
  },
  header: {
    marginBottom: "12px",
  },
  meta: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    flexWrap: "wrap",
  },
  stateBadge: {
    fontSize: "12px",
    fontWeight: 600,
    textTransform: "uppercase",
  },
  taskName: {
    fontSize: "13px",
    color: "#a0a0a0",
  },
  timestamp: {
    fontSize: "12px",
    color: "#666",
  },
  content: {
    fontSize: "14px",
    lineHeight: "1.6",
    color: "#eaeaea",
  },
  imageContainer: {
    marginTop: "12px",
    position: "relative",
    display: "inline-block",
  },
  thumbnail: {
    maxWidth: "300px",
    maxHeight: "200px",
    borderRadius: "6px",
    cursor: "pointer",
    border: "1px solid #2d3748",
  },
  aiStatus: {
    position: "absolute",
    top: "8px",
    right: "8px",
    backgroundColor: "rgba(0, 0, 0, 0.7)",
    padding: "4px 8px",
    borderRadius: "4px",
    fontSize: "14px",
  },
  aiResult: {
    marginTop: "12px",
    padding: "12px",
    backgroundColor: "#1a1a2e",
    borderRadius: "6px",
    border: "1px solid #2d3748",
  },
  aiTitle: {
    fontSize: "13px",
    fontWeight: 600,
    color: "#e94560",
    marginBottom: "8px",
  },
  aiAnalysis: {
    fontSize: "12px",
    color: "#a0a0a0",
    marginBottom: "8px",
  },
  aiCode: {
    margin: 0,
    padding: "8px",
    backgroundColor: "#0f3460",
    borderRadius: "4px",
    fontSize: "11px",
    overflow: "auto",
  },
};
