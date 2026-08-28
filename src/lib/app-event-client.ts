import type { AppCommand } from "../contracts/app-commands.ts";
import type { AppEvent } from "../contracts/app-events.ts";
import { isAppCommand, isAppEvent } from "../contracts/validators.ts";
import type { ContentFreeTelemetry } from "./telemetry.ts";

interface SessionResponse {
  readonly sessionId: string;
  readonly sessionToken: string;
}

export interface AppSession {
  readonly sessionId: string;
  readonly sessionToken: string;
}

export interface AppTransportError {
  readonly category: "app_transport";
  readonly message: string;
  readonly retryable: boolean;
}

export interface AppEventClientOptions {
  readonly onEvent: (event: AppEvent) => void;
  readonly onState: (state: "connecting" | "connected" | "disconnected") => void;
  readonly onError: (error: AppTransportError) => void;
  readonly onSessionUnavailable: () => void;
  readonly telemetry: ContentFreeTelemetry;
  readonly webSocketFactory?: (
    url: string,
    protocols: readonly string[],
  ) => WebSocket;
  readonly retryDelayMs?: number;
  readonly maxReconnectAttempts?: number;
}

export async function createAppSession(): Promise<AppSession> {
  const response = await fetch("/api/sessions", { method: "POST" });
  if (!response.ok) {
    throw new Error("The application session could not be created.");
  }
  const value: unknown = await response.json();
  if (
    typeof value !== "object" ||
    value === null ||
    Array.isArray(value) ||
    Object.keys(value).length !== 2 ||
    !("sessionId" in value) ||
    typeof value.sessionId !== "string" ||
    !/^[0-9a-f-]{36}$/i.test(value.sessionId) ||
    !("sessionToken" in value) ||
    typeof value.sessionToken !== "string" ||
    !/^[A-Za-z0-9_-]{43}$/.test(value.sessionToken)
  ) {
    throw new Error("The application session response was invalid.");
  }
  return value as SessionResponse;
}

export class AppEventClient {
  readonly #sessionId: string;
  readonly #sessionToken: string;
  readonly #options: Required<
    Pick<
      AppEventClientOptions,
      "retryDelayMs" | "maxReconnectAttempts" | "webSocketFactory"
    >
  > &
    Omit<
      AppEventClientOptions,
      "retryDelayMs" | "maxReconnectAttempts" | "webSocketFactory"
    >;
  #socket: WebSocket | null = null;
  #closed = false;
  #attempts = 0;
  #retryTimer: number | undefined;

  constructor(session: AppSession, options: AppEventClientOptions) {
    this.#sessionId = session.sessionId;
    this.#sessionToken = session.sessionToken;
    this.#options = {
      ...options,
      retryDelayMs: options.retryDelayMs ?? 300,
      maxReconnectAttempts: options.maxReconnectAttempts ?? 4,
      webSocketFactory:
        options.webSocketFactory ??
        ((url: string, protocols: readonly string[]) =>
          new WebSocket(url, [...protocols])),
    };
  }

  connect(): void {
    if (this.#closed || this.#socket !== null) {
      return;
    }
    this.#options.onState("connecting");
    const socket = this.#options.webSocketFactory(
      `${webSocketOrigin()}/api/app-events/${this.#sessionId}`,
      ["dcr-app-events.v1", `dcr-session.${this.#sessionToken}`],
    );
    this.#socket = socket;
    socket.addEventListener("open", () => {
      this.#attempts = 0;
      this.#options.onState("connected");
      this.#options.telemetry.record("app_transport_connected", {
        sessionId: this.#sessionId,
      });
    });
    socket.addEventListener("message", (event) => this.#handleMessage(event.data));
    socket.addEventListener("close", (event) =>
      this.#handleClose(socket, event),
    );
    socket.addEventListener("error", () => {
      this.#options.onError({
        category: "app_transport",
        message: "The workspace connection failed. Retry the connection.",
        retryable: true,
      });
    });
  }

  send(command: AppCommand): void {
    if (!isAppCommand(command)) {
      throw new Error("Application command validation failed.");
    }
    if (this.#socket?.readyState !== WebSocket.OPEN) {
      throw new Error(
        "The workspace is reconnecting. Your turn was not sent; submit it again.",
      );
    }
    this.#socket.send(JSON.stringify(command));
  }

  close(): void {
    this.#closed = true;
    if (this.#retryTimer !== undefined) {
      window.clearTimeout(this.#retryTimer);
    }
    this.#socket?.close(1000, "Client closed");
    this.#socket = null;
  }

  #handleMessage(raw: unknown): void {
    if (typeof raw !== "string") {
      this.#rejectMessage();
      return;
    }
    let value: unknown;
    try {
      value = JSON.parse(raw);
    } catch {
      this.#rejectMessage();
      return;
    }
    if (isAppEvent(value)) {
      this.#options.onEvent(value);
      return;
    }
    if (
      typeof value === "object" &&
      value !== null &&
      "type" in value &&
      value.type === "transport.error"
    ) {
      this.#options.onError({
        category: "app_transport",
        message: "The workspace rejected that action. Review it and retry.",
        retryable: false,
      });
      return;
    }
    this.#rejectMessage();
  }

  #rejectMessage(): void {
    this.#options.onError({
      category: "app_transport",
      message: "An invalid workspace event was rejected. Existing work is unchanged.",
      retryable: true,
    });
  }

  #handleClose(socket: WebSocket, event: CloseEvent): void {
    if (this.#socket !== socket) {
      return;
    }
    this.#socket = null;
    this.#options.onState("disconnected");
    this.#options.telemetry.record("app_transport_disconnected", {
      sessionId: this.#sessionId,
    });
    if (event.code === 4404) {
      this.#closed = true;
      this.#options.onSessionUnavailable();
      return;
    }
    if (this.#closed || this.#attempts >= this.#options.maxReconnectAttempts) {
      this.#options.onError({
        category: "app_transport",
        message:
          "The workspace is disconnected. Reconnect, then submit unsent turns again.",
        retryable: true,
      });
      return;
    }
    this.#attempts += 1;
    this.#retryTimer = window.setTimeout(
      () => this.connect(),
      this.#options.retryDelayMs * 2 ** (this.#attempts - 1),
    );
  }
}

function webSocketOrigin(): string {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${window.location.host}`;
}
