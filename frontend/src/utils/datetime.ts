/** 应用时间工具
 *
 * 统一处理 API 时间解析、应用时区展示、按天分组与持续时长计算。
 */

const DEFAULT_APP_TIMEZONE = "Asia/Shanghai";
const ISO_OFFSET_PATTERN = /(Z|[+-]\d{2}:\d{2})$/;
const DATE_KEY_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
let appTimezoneName = DEFAULT_APP_TIMEZONE;

function getAppTimezone(): string {
  return appTimezoneName;
}

function buildFormatter(
  locale: string,
  options: Intl.DateTimeFormatOptions,
  timeZone = getAppTimezone()
): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat(locale, {
    ...options,
    timeZone,
  });
}

function createUtcDateFromDateKey(dateKey: string): Date | null {
  if (!DATE_KEY_PATTERN.test(dateKey)) {
    return null;
  }

  const [yearText, monthText, dayText] = dateKey.split("-");
  const yearValue = Number.parseInt(yearText, 10);
  const monthValue = Number.parseInt(monthText, 10);
  const dayValue = Number.parseInt(dayText, 10);
  return new Date(Date.UTC(yearValue, monthValue - 1, dayValue, 12, 0, 0));
}

function normalizeApiDateText(rawDateText: string): string {
  const trimmedDateText = rawDateText.trim();
  if (ISO_OFFSET_PATTERN.test(trimmedDateText)) {
    return trimmedDateText;
  }

  if (DATE_KEY_PATTERN.test(trimmedDateText)) {
    return `${trimmedDateText}T00:00:00Z`;
  }

  return `${trimmedDateText}Z`;
}

function buildDateKeyFromDate(inputDate: Date): string {
  const datePartList = buildFormatter("en-US", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(inputDate);

  const datePartValueByType = new Map<string, string>();
  for (const datePart of datePartList) {
    datePartValueByType.set(datePart.type, datePart.value);
  }

  const yearValue = datePartValueByType.get("year") ?? "0000";
  const monthValue = datePartValueByType.get("month") ?? "00";
  const dayValue = datePartValueByType.get("day") ?? "00";
  return `${yearValue}-${monthValue}-${dayValue}`;
}

function formatCalendarDateKey(
  dateKey: string,
  options: Intl.DateTimeFormatOptions,
  locale = "zh-CN"
): string {
  const calendarDate = createUtcDateFromDateKey(dateKey);
  if (!calendarDate) {
    return dateKey;
  }

  return buildFormatter(locale, options, "UTC").format(calendarDate);
}

export function configureAppTimezone(nextAppTimezoneName: string | null | undefined): void {
  const normalizedTimezoneName = nextAppTimezoneName?.trim();
  if (!normalizedTimezoneName) {
    appTimezoneName = DEFAULT_APP_TIMEZONE;
    return;
  }

  try {
    buildFormatter("en-US", { year: "numeric" }, normalizedTimezoneName);
    appTimezoneName = normalizedTimezoneName;
  } catch {
    appTimezoneName = DEFAULT_APP_TIMEZONE;
  }
}

export function parseApiDate(rawDateText: string): Date | null {
  if (!rawDateText) {
    return null;
  }

  const parsedDate = new Date(normalizeApiDateText(rawDateText));
  if (Number.isNaN(parsedDate.getTime())) {
    return null;
  }

  return parsedDate;
}

export function formatInAppTimezone(
  rawDateText: string,
  options: Intl.DateTimeFormatOptions,
  locale = "en-US"
): string {
  const parsedDate = parseApiDate(rawDateText);
  if (!parsedDate) {
    return rawDateText;
  }

  return buildFormatter(locale, options).format(parsedDate);
}

export function formatMonthDay(rawDateText: string): string {
  return formatInAppTimezone(
    rawDateText,
    {
      month: "short",
      day: "numeric",
    },
    "en-US"
  );
}

export function formatHourMinute(rawDateText: string): string {
  return formatInAppTimezone(
    rawDateText,
    {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    },
    "en-US"
  );
}

export function formatDateTime(rawDateText: string): string {
  return formatInAppTimezone(
    rawDateText,
    {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    },
    "en-US"
  );
}

export function formatMonthDayTime(rawDateText: string): string {
  return formatInAppTimezone(
    rawDateText,
    {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    },
    "zh-CN"
  );
}

export function getAppDateKey(rawDateText: string): string {
  const parsedDate = parseApiDate(rawDateText);
  if (!parsedDate) {
    return rawDateText;
  }

  return buildDateKeyFromDate(parsedDate);
}

export function formatDateGroupLabel(
  dateKey: string,
  nowDate: Date = new Date()
): string {
  const todayDateKey = buildDateKeyFromDate(nowDate);
  const yesterdayDateKey = buildDateKeyFromDate(
    new Date(nowDate.getTime() - 24 * 60 * 60 * 1000)
  );

  if (dateKey === todayDateKey) {
    return "Today";
  }
  if (dateKey === yesterdayDateKey) {
    return "Yesterday";
  }

  return formatCalendarDateKey(
    dateKey,
    {
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "long",
    },
    "zh-CN"
  );
}

export function formatDateKeyLabel(dateKey: string): string {
  return formatCalendarDateKey(
    dateKey,
    {
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "long",
    },
    "zh-CN"
  );
}

export function groupItemsByAppDate<T>(
  itemList: T[],
  getDateText: (item: T) => string
): Array<[string, T[]]> {
  const itemListByDateKey = new Map<string, T[]>();

  for (const item of itemList) {
    const dateKey = getAppDateKey(getDateText(item));
    if (!itemListByDateKey.has(dateKey)) {
      itemListByDateKey.set(dateKey, []);
    }
    itemListByDateKey.get(dateKey)?.push(item);
  }

  return Array.from(itemListByDateKey.entries()).sort(([leftDateKey], [rightDateKey]) =>
    rightDateKey.localeCompare(leftDateKey)
  );
}

export function calculateDuration(
  startDateText: string,
  endDateText: string | null,
  nowDate: Date = new Date()
): string {
  const startDate = parseApiDate(startDateText);
  const endDate = endDateText ? parseApiDate(endDateText) : nowDate;

  if (!startDate || !endDate) {
    return "0m";
  }

  const durationMilliseconds = Math.max(0, endDate.getTime() - startDate.getTime());
  const durationDays = Math.floor(durationMilliseconds / (1000 * 60 * 60 * 24));
  const durationHours = Math.floor(
    (durationMilliseconds % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60)
  );
  const durationMinutes = Math.floor(
    (durationMilliseconds % (1000 * 60 * 60)) / (1000 * 60)
  );

  if (durationDays > 0) {
    return `${durationDays}d ${durationHours}h`;
  }
  if (durationHours > 0) {
    return `${durationHours}h ${durationMinutes}m`;
  }
  return `${durationMinutes}m`;
}

export function toTimestampValue(rawDateText: string): number {
  const parsedDate = parseApiDate(rawDateText);
  return parsedDate ? parsedDate.getTime() : 0;
}
