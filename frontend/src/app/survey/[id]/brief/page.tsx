"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, CheckCircle2, FileDown, Send, Sparkles, TriangleAlert, WifiOff } from "lucide-react";

import { useSurvey } from "@/components/survey/SurveyContext";
import { Badge, Button, ErrorNote, InfoNote, Reveal, Spinner } from "@/components/ui";
import { API_BASE_URL, analystStatus, cachedReport, listFindings, streamChat, streamReport, type ChatTurn } from "@/lib/api/survey";
import type { AnalystStatus, Finding } from "@/lib/sceneTypes";
import { getToken } from "@/lib/api/http";

function inline(text: string): React.ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|_[^_]+_)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i} className="font-semibold text-polar-night">{part.slice(2, -2)}</strong>;
    if (part.startsWith("_") && part.endsWith("_") && part.length > 2) return <em key={i} className="text-slate-ice">{part.slice(1, -1)}</em>;
    return part;
  });
}

function Markdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  text.split("\n").forEach((line, index) => {
    if (line.startsWith("## ")) blocks.push(<h3 key={index} className="mt-6 border-b border-glacier-300/60 pb-1.5 text-lg font-semibold text-deep-ice first:mt-0">{line.slice(3)}</h3>);
    else if (/^\s*[-*] /.test(line)) blocks.push(<li key={index} className="ml-5 list-disc text-[0.93rem] leading-relaxed text-polar-night">{inline(line.replace(/^\s*[-*] /, ""))}</li>);
    else if (/^\d+\.\s/.test(line)) blocks.push(<p key={index} className="mt-2 flex gap-3 text-[0.93rem] leading-relaxed text-polar-night"><span className="mono font-semibold text-station-orange">{line.match(/^\d+/)![0]}</span><span>{inline(line.replace(/^\d+\.\s/, ""))}</span></p>);
    else if (line.trim()) blocks.push(<p key={index} className="mt-2 text-[0.93rem] leading-relaxed text-polar-night">{inline(line)}</p>);
  });
  return <div>{blocks}</div>;
}

export default function Brief() {
  const { id } = useSurvey();
  const [appOrigin, setAppOrigin] = useState("");
  const [status, setStatus] = useState<AnalystStatus | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [text, setText] = useState("");
  const [tools, setTools] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [mode, setMode] = useState<string | null>(null);
  const [unverified, setUnverified] = useState<string[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [thread, setThread] = useState<ChatTurn[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [chatNotice, setChatNotice] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);
  const chatAbort = useRef<AbortController | null>(null);
  const chatEnd = useRef<HTMLDivElement | null>(null);

  useEffect(() => setAppOrigin(window.location.origin), []);

  useEffect(() => {
    analystStatus().then(setStatus).catch(() => setStatus(null));
    listFindings(id).then(setFindings).catch(() => setFindings([]));
    cachedReport(id)
      .then((r) => {
        if (r.available && r.report) {
          setText(r.report.text);
          setMode(r.report.mode);
          setUnverified(r.report.unverified_numbers);
          setNotice(r.report.notice);
        }
      })
      .catch(() => undefined);
    return () => abort.current?.abort();
  }, [id]);

  async function generate(forceOffline = false) {
    abort.current?.abort();
    abort.current = new AbortController();
    setStreaming(true);
    setError(null);
    setText("");
    setTools([]);
    setNotice(null);
    setUnverified([]);
    try {
      await streamReport(
        id,
        (event) => {
          if (event.event === "tool") setTools((t) => [...t, event.label]);
          else if (event.event === "text") setText((t) => t + event.text);
          else if (event.event === "reset") setText("");
          else if (event.event === "notice") setNotice(event.text);
          else if (event.event === "done") {
            setMode(event.mode);
            setUnverified(event.unverified_numbers);
          }
        },
        forceOffline,
        abort.current.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") setError(err instanceof Error ? err.message : "Report failed.");
    } finally {
      setStreaming(false);
    }
  }

  async function ask(event: React.FormEvent) {
    event.preventDefault();
    const q = question.trim();
    if (!q || asking) return;
    const history = thread.slice(-12);
    setThread((t) => [...t, { role: "user", content: q }]);
    setQuestion("");
    setAsking(true);
    setChatNotice(null);
    setPending("");
    chatAbort.current?.abort();
    chatAbort.current = new AbortController();
    let answer = "";
    try {
      await streamChat(
        id,
        q,
        history,
        (event) => {
          if (event.event === "text") {
            answer += event.text;
            setPending(answer);
          } else if (event.event === "reset") {
            answer = "";
            setPending("");
          } else if (event.event === "notice") setChatNotice(event.text);
        },
        chatAbort.current.signal,
      );
      setThread((t) => [...t, { role: "assistant", content: answer }]);
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setThread((t) => [...t, { role: "assistant", content: `Could not answer: ${err instanceof Error ? err.message : "request failed"}` }]);
      }
    } finally {
      setPending(null);
      setAsking(false);
    }
  }

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [thread, pending]);

  const online = status?.available;
  const token = getToken();
  // The PDF's "open in app" links point back at this site, so pass our own origin (known only on the client).
  const query = new URLSearchParams();
  if (token) query.set("token", token);
  if (appOrigin) query.set("app_url", appOrigin);
  const pdfUrl = `${API_BASE_URL}/api/analyst/${id}/report.pdf${query.size ? `?${query}` : ""}`;

  return (
    <div className="mx-auto grid w-full max-w-[1500px] flex-1 gap-6 px-5 py-8 sm:px-8 lg:grid-cols-[minmax(0,1fr)_23rem]">
      <div className="space-y-5">
        <Reveal>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="max-w-2xl">
              <p className="eyebrow">AI analyst</p>
              <h1 className="mt-1 text-3xl font-semibold tracking-tight text-polar-night">Situation report and response plan.</h1>
              <p className="mt-2 text-[0.95rem] leading-relaxed text-slate-ice">
                The analyst reads derived statistics only (heights, class areas, flood and landing results, slope, validation) through read-only tools. Raw imagery never leaves this machine.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button loading={streaming} onClick={() => generate(false)}>
                <Sparkles className="h-4 w-4" strokeWidth={1.75} /> {text ? "Regenerate" : "Generate brief"}
              </Button>
              {text && (
                <a href={pdfUrl} className="btn btn-ghost" download>
                  <FileDown className="h-4 w-4" strokeWidth={1.5} /> PDF
                </a>
              )}
            </div>
          </div>
        </Reveal>

        {error && <ErrorNote message={error} />}

        <Reveal delay={0.05}>
          <div className="card min-h-[26rem] p-6 sm:p-8">
            {tools.length > 0 && (
              <div className="mb-5 flex flex-wrap gap-2">
                {tools.map((tool) => (
                  <Badge key={tool} tone="ice"><CheckCircle2 className="h-3.5 w-3.5" strokeWidth={2} /> {tool}</Badge>
                ))}
              </div>
            )}
            {text ? (
              <>
                <Markdown text={text} />
                {streaming && <span className="ml-1 inline-block h-4 w-2 animate-pulse bg-station-orange align-middle" />}
              </>
            ) : streaming ? (
              <div className="flex items-center gap-3 text-slate-ice"><Spinner /> Reading scene statistics…</div>
            ) : (
              <div className="flex h-full min-h-[20rem] flex-col items-center justify-center text-center">
                <Bot className="h-10 w-10 text-glacier-500" strokeWidth={1.2} />
                <p className="mt-3 max-w-sm text-sm leading-relaxed text-slate-ice">
                  No brief yet. Run the flood, landing-zone or slope tools on the Hazards screen first so the analyst has findings to work from, then generate the brief.
                </p>
              </div>
            )}
          </div>
        </Reveal>

        {(notice || mode) && (
          <div className="flex flex-wrap items-center gap-3 text-xs text-slate-ice">
            {mode && <Badge tone={mode === "online" ? "aurora" : "muted"}>{mode === "online" ? "Online analyst" : "Offline template analyst"}</Badge>}
            {notice && <span className="flex items-center gap-1.5"><WifiOff className="h-3.5 w-3.5" strokeWidth={1.5} /> {notice}</span>}
          </div>
        )}
        {unverified.length > 0 && (
          <InfoNote className="!border-station-orange/40 !bg-station-orange/5 !text-polar-night">
            <span className="flex items-center gap-2 font-semibold text-station-orange"><TriangleAlert className="h-4 w-4" strokeWidth={1.75} /> Numbers not found in the statistics</span>
            <span className="mt-1 block">These figures in the generated text could not be matched to a tool result, so treat them with caution: <span className="mono">{unverified.join(", ")}</span></span>
          </InfoNote>
        )}
      </div>

      <div className="space-y-5">
        <Reveal delay={0.1}>
          <div className="card p-4">
            <p className="eyebrow">Analyst status</p>
            <div className="mt-3 flex items-center gap-2">
              <span className={`h-2.5 w-2.5 rounded-full ${online ? "bg-aurora" : "bg-slate-ice"}`} />
              <span className="text-sm font-semibold text-polar-night">{online ? `Online (${status?.model})` : "Offline template mode"}</span>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-slate-ice">{status?.note}</p>
            {online && <Button variant="ghost" size="sm" className="mt-3 w-full" onClick={() => generate(true)} disabled={streaming}>Generate offline instead</Button>}
          </div>
        </Reveal>

        <Reveal delay={0.14}>
          <div className="card p-4">
            <p className="eyebrow">Findings the analyst sees</p>
            <ul className="mt-3 space-y-2">
              {findings.length === 0 && <li className="text-xs text-slate-ice">None recorded. Add some on the Hazards screen.</li>}
              {findings.slice(-6).reverse().map((f) => (
                <li key={f.id} className="rounded-lg bg-white/70 p-2.5 text-xs leading-snug text-polar-night"><b className="capitalize text-deep-ice">{f.tool}:</b> {f.text}</li>
              ))}
            </ul>
          </div>
        </Reveal>

        <Reveal delay={0.18}>
          <div className="card flex flex-col p-4">
            <div className="flex items-center justify-between">
              <p className="eyebrow">Ask about this scene</p>
              {thread.length > 0 && (
                <button type="button" className="text-[0.7rem] text-slate-ice underline-offset-2 hover:underline" onClick={() => { setThread([]); setChatNotice(null); }}>
                  Clear
                </button>
              )}
            </div>

            <div className="mt-3 max-h-[26rem] min-h-[9rem] space-y-2.5 overflow-y-auto pr-1">
              {thread.length === 0 && pending === null && (
                <div className="space-y-2">
                  <p className="text-xs leading-relaxed text-slate-ice">
                    Ask follow-up questions about this scene. The analyst re-reads the statistics each turn and remembers the conversation.
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {["How many vehicles are there?", "What floods first?", "Where can a helicopter land?", "How accurate is this?"].map((suggestion) => (
                      <button
                        key={suggestion}
                        type="button"
                        onClick={() => setQuestion(suggestion)}
                        className="rounded-full border border-glacier-300/70 bg-white/60 px-2.5 py-1 text-[0.7rem] text-deep-ice transition-colors hover:bg-glacier-100"
                      >
                        {suggestion}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {thread.map((turn, index) =>
                turn.role === "user" ? (
                  <p key={index} className="ml-6 rounded-lg bg-deep-ice px-3 py-2 text-xs font-semibold text-white">{turn.content}</p>
                ) : (
                  <p key={index} className="mr-6 whitespace-pre-wrap rounded-lg bg-white/80 px-3 py-2 text-xs leading-relaxed text-polar-night">{turn.content}</p>
                ),
              )}
              {pending !== null && (
                <p className="mr-6 whitespace-pre-wrap rounded-lg bg-white/80 px-3 py-2 text-xs leading-relaxed text-polar-night">
                  {pending}
                  <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-station-orange align-middle" />
                </p>
              )}
              {asking && pending === "" && <div className="flex items-center gap-2 text-xs text-slate-ice"><Spinner className="h-4 w-4" /> Reading statistics…</div>}
              <div ref={chatEnd} />
            </div>

            <form onSubmit={ask} className="mt-3 flex gap-2">
              <input className="ctl" placeholder="How many vehicles are there?" value={question} onChange={(e) => setQuestion(e.target.value)} aria-label="Question" />
              <button className="btn btn-primary btn-sm" type="submit" disabled={asking || !question.trim()} aria-label="Ask"><Send className="h-4 w-4" strokeWidth={1.75} /></button>
            </form>
            {chatNotice && <p className="mt-2 flex items-center gap-1.5 text-[0.7rem] leading-snug text-slate-ice"><WifiOff className="h-3 w-3" strokeWidth={1.5} /> {chatNotice}</p>}
            <p className="mt-2 text-[0.7rem] leading-snug text-slate-ice">Answers use only the exposed statistics — never the raw imagery.</p>
          </div>
        </Reveal>
      </div>
    </div>
  );
}
