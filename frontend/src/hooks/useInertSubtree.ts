/** Inert-subtree hook
 *
 * Keeps a mounted subtree fully non-interactive while stale UI remains visible
 * during an async transition.
 */

import { useLayoutEffect, useRef } from "react";

function setInertSubtreeState(
  lockedSubtreeElement: HTMLElement,
  isSubtreeInteractionLocked: boolean
): void {
  if ("inert" in lockedSubtreeElement) {
    lockedSubtreeElement.inert = isSubtreeInteractionLocked;
  }

  if (isSubtreeInteractionLocked) {
    lockedSubtreeElement.setAttribute("inert", "");
    return;
  }

  lockedSubtreeElement.removeAttribute("inert");
}

export function useInertSubtree<T extends HTMLElement>(
  isSubtreeInteractionLocked: boolean
) {
  const lockedSubtreeElementRef = useRef<T | null>(null);

  useLayoutEffect(() => {
    const lockedSubtreeElement = lockedSubtreeElementRef.current;
    if (!lockedSubtreeElement) {
      return;
    }

    setInertSubtreeState(lockedSubtreeElement, isSubtreeInteractionLocked);
    if (!isSubtreeInteractionLocked) {
      return;
    }

    const activeDocumentElement = document.activeElement;
    if (
      activeDocumentElement instanceof HTMLElement &&
      lockedSubtreeElement.contains(activeDocumentElement)
    ) {
      activeDocumentElement.blur();
    }

    return () => {
      setInertSubtreeState(lockedSubtreeElement, false);
    };
  }, [isSubtreeInteractionLocked]);

  return lockedSubtreeElementRef;
}
