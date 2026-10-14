import type { EventItem } from "./types";
export type FeedMessage = EventItem | { type: "event_updated"; event: EventItem };
export function eventFeedReducer(events: EventItem[], message: FeedMessage): EventItem[] {
  if ("event" in message && message.type === "event_updated") {
    return events.map((event) => event.id === message.event.id ? message.event : event);
  }
  if ("id" in message && events.some((event) => event.id === message.id)) return events;
  return [...events, message as EventItem].slice(-200);
}
