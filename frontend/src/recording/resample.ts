/**
 * Sample-rate conversion by windowed-sinc interpolation. Written out here (instead of using the browser's offline audio context)
 * so that the same samples always give the same bytes, in every browser, and so it can be tested without one.
 *
 * The kernel is a Blackman-windowed sinc whose cut-off is the lower of the two Nyquist frequencies, so converting down (48 kHz to
 * 16 kHz) removes what 16 kHz cannot represent instead of folding it back as noise.
 */
const HALF_WIDTH = 8; // zero crossings of the kernel on each side, measured at the lower rate
const TABLE_RES = 256; // kernel table entries per input sample

interface Kernel {
  table: Float64Array;
  reach: number;
  ratio: number;
}

function buildKernel(inRate: number, outRate: number): Kernel {
  const ratio = inRate / outRate;
  const cutoff = Math.min(1, outRate / inRate);
  const reach = HALF_WIDTH / cutoff;
  const size = Math.ceil(reach * TABLE_RES) + 2;
  const table = new Float64Array(size);
  for (let i = 0; i < size; i++) {
    const x = i / TABLE_RES;
    const u = Math.min(1, x / reach);
    const window = 0.42 + 0.5 * Math.cos(Math.PI * u) + 0.08 * Math.cos(2 * Math.PI * u);
    const arg = Math.PI * cutoff * x;
    table[i] = (x === 0 ? 1 : Math.sin(arg) / arg) * window;
  }
  return { table, reach, ratio };
}

function resampleRange(input: Float32Array, out: Float32Array, from: number, to: number, kernel: Kernel): void {
  const { table, reach, ratio } = kernel;
  const last = table.length - 2;
  for (let i = from; i < to; i++) {
    const centre = i * ratio;
    const lo = Math.max(0, Math.ceil(centre - reach));
    const hi = Math.min(input.length - 1, Math.floor(centre + reach));
    let sum = 0;
    let weights = 0;
    for (let j = lo; j <= hi; j++) {
      const pos = Math.abs(j - centre) * TABLE_RES;
      const k = Math.min(last, Math.floor(pos));
      const w = table[k]! + (table[k + 1]! - table[k]!) * (pos - k);
      sum += (input[j] as number) * w;
      weights += w;
    }
    out[i] = weights > 1e-12 ? sum / weights : 0;
  }
}

export function resample(input: Float32Array, inRate: number, outRate: number): Float32Array {
  if (inRate === outRate) return input.slice();
  const out = new Float32Array(Math.floor(input.length / (inRate / outRate)));
  resampleRange(input, out, 0, out.length, buildKernel(inRate, outRate));
  return out;
}

/** The same conversion in slices, yielding to the browser between them so a long recording does not freeze the page. */
export async function resampleAsync(input: Float32Array, inRate: number, outRate: number, slice = 200_000): Promise<Float32Array> {
  if (inRate === outRate) return input.slice();
  const kernel = buildKernel(inRate, outRate);
  const out = new Float32Array(Math.floor(input.length / kernel.ratio));
  for (let from = 0; from < out.length; from += slice) {
    resampleRange(input, out, from, Math.min(out.length, from + slice), kernel);
    if (from + slice < out.length) await new Promise<void>((resolve) => setTimeout(resolve, 0));
  }
  return out;
}
