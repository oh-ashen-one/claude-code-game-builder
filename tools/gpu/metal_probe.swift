import Metal
import Foundation
// gpu probe: one 1 MiB blit fill; prints "ok <ms>" or exits non-zero. Caller enforces the timeout.
let t0 = Date()
guard let dev = MTLCreateSystemDefaultDevice(), let q = dev.makeCommandQueue(),
      let buf = dev.makeBuffer(length: 1 << 20, options: []), let cb = q.makeCommandBuffer(),
      let enc = cb.makeBlitCommandEncoder() else { print("no-device"); exit(2) }
enc.fill(buffer: buf, range: 0..<(1 << 20), value: 7)
enc.endEncoding(); cb.commit(); cb.waitUntilCompleted()
let ms = Int(Date().timeIntervalSince(t0) * 1000)
if cb.status == .completed { print("ok \(ms)"); exit(0) } else { print("status \(cb.status.rawValue) \(ms)"); exit(1) }
