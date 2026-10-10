import type {
  AnalysisResult, BaselineListResponse, ErrorCode, ErrorResponse, HealthResponse, SampleIndex, StatusResponse,
} from './types';

/** Everything that can go wrong talking to the API, in one shape the UI can show. */
export type ApiErrorCode = ErrorCode | 'NETWORK_ERROR' | 'HTTP_ERROR' | 'ABORTED' | 'BAD_RESPONSE';

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly detail: string;
  readonly status: number;
  readonly analysisId: string | null;

  constructor(code: ApiErrorCode, detail: string, status = 0, analysisId: string | null = null) {
    super(detail);
    this.name = 'ApiError';
    this.code = code;
    this.detail = detail;
    this.status = status;
    this.analysisId = analysisId;
  }
}

export interface AnalyzeParams {
  baselineId: string;
  passageId: string;
  manualTranscript?: string;
}

export interface AnalyzeOptions {
  signal?: AbortSignal;
  /** Called while the file is being sent. After 100 % the server is analysing (the API reports no finer progress). */
  onUploadProgress?: (loaded: number, total: number) => void;
}

export interface ApiClient {
  health(signal?: AbortSignal): Promise<HealthResponse>;
  baselines(signal?: AbortSignal): Promise<BaselineListResponse>;
  result(analysisId: string, signal?: AbortSignal): Promise<AnalysisResult>;
  status(analysisId: string, signal?: AbortSignal): Promise<StatusResponse>;
  analyze(file: File, params: AnalyzeParams, options?: AnalyzeOptions): Promise<AnalysisResult>;
}

const API_PREFIX = '/api/v1';

/** The upload endpoint accepts WAV and MP3 only, and checks that extension and content type agree. */
export function normalizeAudioFile(file: File): File {
  const name = file.name;
  const lower = name.toLowerCase();
  const type = lower.endsWith('.mp3') ? 'audio/mpeg' : lower.endsWith('.wav') ? 'audio/wav' : file.type;
  return type === file.type ? file : new File([file], name, { type, lastModified: file.lastModified });
}

export function isSupportedAudioName(name: string): boolean {
  return /\.(wav|mp3)$/i.test(name);
}

async function readError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    /* not JSON */
  }
  if (body && typeof body === 'object' && 'error' in body && 'detail' in body) {
    const e = body as ErrorResponse;
    return new ApiError(e.error, e.detail, response.status, e.analysis_id ?? null);
  }
  return new ApiError('HTTP_ERROR', `The server answered ${response.status} ${response.statusText}.`.trim(), response.status);
}

export function createClient(getBase: () => string = () => ''): ApiClient {
  const url = (path: string) => `${getBase()}${API_PREFIX}${path}`;

  async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
    let response: Response;
    try {
      response = await fetch(url(path), { headers: { Accept: 'application/json' }, signal });
    } catch (cause) {
      if (signal?.aborted) throw new ApiError('ABORTED', 'The request was cancelled.');
      throw new ApiError('NETWORK_ERROR', 'The API could not be reached. Is the backend running?');
    }
    if (!response.ok) throw await readError(response);
    try {
      return (await response.json()) as T;
    } catch {
      throw new ApiError('BAD_RESPONSE', 'The API answered with something that is not JSON.', response.status);
    }
  }

  return {
    health: (signal) => getJson<HealthResponse>('/health', signal),
    baselines: (signal) => getJson<BaselineListResponse>('/baselines', signal),
    result: (id, signal) => getJson<AnalysisResult>(`/result/${encodeURIComponent(id)}`, signal),
    status: (id, signal) => getJson<StatusResponse>(`/status/${encodeURIComponent(id)}`, signal),

    analyze(file, params, options = {}) {
      return new Promise<AnalysisResult>((resolve, reject) => {
        const form = new FormData();
        form.append('participant_audio', normalizeAudioFile(file), file.name);
        form.append('baseline_id', params.baselineId);
        form.append('passage_id', params.passageId);
        if (params.manualTranscript?.trim()) form.append('manual_transcript', params.manualTranscript.trim());

        const xhr = new XMLHttpRequest();
        xhr.open('POST', url('/analyze'));
        xhr.responseType = 'text';
        xhr.setRequestHeader('Accept', 'application/json');
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) options.onUploadProgress?.(event.loaded, event.total);
        };
        xhr.onerror = () => reject(new ApiError('NETWORK_ERROR', 'The API could not be reached. Is the backend running?'));
        xhr.onabort = () => reject(new ApiError('ABORTED', 'The analysis was cancelled.'));
        xhr.onload = () => {
          let body: unknown = null;
          try {
            body = JSON.parse(xhr.responseText);
          } catch {
            /* handled below */
          }
          if (xhr.status >= 200 && xhr.status < 300 && body && typeof body === 'object') {
            resolve(body as AnalysisResult);
          } else if (body && typeof body === 'object' && 'error' in body && 'detail' in body) {
            const e = body as ErrorResponse;
            reject(new ApiError(e.error, e.detail, xhr.status, e.analysis_id ?? null));
          } else {
            reject(new ApiError('HTTP_ERROR', `The server answered ${xhr.status}.`, xhr.status));
          }
        };
        if (options.signal) {
          if (options.signal.aborted) return reject(new ApiError('ABORTED', 'The analysis was cancelled.'));
          options.signal.addEventListener('abort', () => xhr.abort(), { once: true });
        }
        xhr.send(form);
      });
    },
  };
}

// ---- demo samples (static files shipped with the dashboard) --------------------------------------------------------------
export const SAMPLES_BASE = `${import.meta.env.BASE_URL}samples`;

async function getStatic<T>(path: string, missing: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { signal });
  } catch {
    if (signal?.aborted) throw new ApiError('ABORTED', 'The request was cancelled.');
    throw new ApiError('NETWORK_ERROR', missing);
  }
  if (!response.ok) throw new ApiError('HTTP_ERROR', missing, response.status);
  try {
    return (await response.json()) as T;
  } catch {
    if (signal?.aborted) throw new ApiError('ABORTED', 'The request was cancelled.');
    throw new ApiError('BAD_RESPONSE', missing, response.status);
  }
}

export const fetchSampleIndex = (signal?: AbortSignal): Promise<SampleIndex> =>
  getStatic<SampleIndex>(`${SAMPLES_BASE}/index.json`, 'The demo samples are not installed.', signal);

export const fetchSampleResult = (file: string, signal?: AbortSignal): Promise<AnalysisResult> =>
  getStatic<AnalysisResult>(`${SAMPLES_BASE}/${file}`, 'The sample result could not be loaded.', signal);

/** The API contract version this dashboard was built against (from the OpenAPI snapshot its types were generated from). */
export const CLIENT_CONTRACT_VERSION: string = typeof __CONTRACT_VERSION__ === 'string' ? __CONTRACT_VERSION__ : 'unknown';
