class Capture extends AudioWorkletProcessor {
  constructor() { super(); this.buffer = []; this.position = 0; }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (!input) return true;
    // Carry fractional position across render quanta for 44.1/48 kHz devices.
    const ratio = sampleRate / 24000;
    for (; this.position < input.length; this.position += ratio) {
      const i = Math.floor(this.position);
      const v = input[i];
      this.buffer.push(Math.max(-32768, Math.min(32767, Math.round(v * 32767))));
    }
    this.position -= input.length;
    if (this.buffer.length >= 2400) {
      const frame = new Int16Array(this.buffer.splice(0, 2400));
      this.port.postMessage(frame.buffer, [frame.buffer]);
    }
    return true;
  }
}
registerProcessor('capture', Capture);
