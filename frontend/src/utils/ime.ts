/** 输入法兼容工具
 *
 * 判断回车键是否应该触发提交，并避免在中文输入法合成阶段误提交。
 */

interface EnterKeyEventLike {
  key: string;
  shiftKey: boolean;
  nativeEvent?: {
    isComposing?: boolean;
  };
}

export function shouldSubmitOnEnter(
  keyboardEventLike: EnterKeyEventLike,
  isComposing: boolean
): boolean {
  return (
    keyboardEventLike.key === "Enter" &&
    !keyboardEventLike.shiftKey &&
    !isComposing &&
    !keyboardEventLike.nativeEvent?.isComposing
  );
}
