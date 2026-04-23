/** 中文输入法安全的回车提交 hook
 *
 * 在 textarea 合成输入期间忽略 Enter，避免中文输入法候选确认时误触发发送。
 */

import { useCallback, useRef } from "react";
import type { KeyboardEvent } from "react";
import { shouldSubmitOnEnter } from "../utils/ime";

interface UseImeAwareEnterSubmitOptions {
  onSubmit: () => void;
  isEnabled: boolean;
}

export function useImeAwareEnterSubmit({
  onSubmit,
  isEnabled,
}: UseImeAwareEnterSubmitOptions): {
  handleCompositionStart: () => void;
  handleCompositionEnd: () => void;
  handleKeyDown: (keyboardEvent: KeyboardEvent<HTMLTextAreaElement>) => void;
} {
  const isComposingRef = useRef(false);

  const handleCompositionStart = useCallback(() => {
    isComposingRef.current = true;
  }, []);

  const handleCompositionEnd = useCallback(() => {
    isComposingRef.current = false;
  }, []);

  const handleKeyDown = useCallback(
    (keyboardEvent: KeyboardEvent<HTMLTextAreaElement>) => {
      if (!isEnabled) {
        return;
      }

      if (!shouldSubmitOnEnter(keyboardEvent, isComposingRef.current)) {
        return;
      }

      keyboardEvent.preventDefault();
      onSubmit();
    },
    [isEnabled, onSubmit]
  );

  return {
    handleCompositionStart,
    handleCompositionEnd,
    handleKeyDown,
  };
}
