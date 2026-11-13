// Draws the app icon: two Shabbat candles on the display's navy. Run: swift tools/make-icon.swift <out.png>
import AppKit

let size = 1024.0
let space = CGColorSpaceCreateDeviceRGB()
let ctx = CGContext(data: nil, width: Int(size), height: Int(size), bitsPerComponent: 8, bytesPerRow: 0, space: space,
                    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
func rgb(_ hex: Int, _ a: Double = 1) -> CGColor {
    CGColor(red: Double((hex >> 16) & 255) / 255, green: Double((hex >> 8) & 255) / 255, blue: Double(hex & 255) / 255, alpha: a)
}
// Background: navy, a little lighter toward the top.
let back = CGGradient(colorsSpace: space, colors: [rgb(0x1B2B45), rgb(0x0D1726)] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(back, start: CGPoint(x: 0, y: size), end: CGPoint(x: 0, y: 0), options: [])
for x in [372.0, 652.0] {
    // Glow
    let glow = CGGradient(colorsSpace: space, colors: [rgb(0xE5BA5E, 0.38), rgb(0xE5BA5E, 0)] as CFArray, locations: [0, 1])!
    ctx.drawRadialGradient(glow, startCenter: CGPoint(x: x, y: 640), startRadius: 0, endCenter: CGPoint(x: x, y: 640), endRadius: 230, options: [])
    // Candle
    ctx.setFillColor(rgb(0xEFE9DC))
    ctx.addPath(CGPath(roundedRect: CGRect(x: x - 46, y: 250, width: 92, height: 290), cornerWidth: 14, cornerHeight: 14, transform: nil))
    ctx.fillPath()
    // Holder
    ctx.setFillColor(rgb(0xE5BA5E))
    ctx.addPath(CGPath(roundedRect: CGRect(x: x - 86, y: 206, width: 172, height: 56), cornerWidth: 20, cornerHeight: 20, transform: nil))
    ctx.fillPath()
    // Wick
    ctx.setFillColor(rgb(0x26354F))
    ctx.fill(CGRect(x: x - 4, y: 540, width: 8, height: 30))
    // Flame: a teardrop
    let flame = CGMutablePath()
    flame.move(to: CGPoint(x: x, y: 770))
    flame.addCurve(to: CGPoint(x: x, y: 562), control1: CGPoint(x: x + 96, y: 660), control2: CGPoint(x: x + 70, y: 562))
    flame.addCurve(to: CGPoint(x: x, y: 770), control1: CGPoint(x: x - 70, y: 562), control2: CGPoint(x: x - 96, y: 660))
    ctx.setFillColor(rgb(0xE5BA5E))
    ctx.addPath(flame)
    ctx.fillPath()
    ctx.setFillColor(rgb(0xFFF1C9))
    ctx.fillEllipse(in: CGRect(x: x - 22, y: 580, width: 44, height: 78))
}
let image = NSBitmapImageRep(cgImage: ctx.makeImage()!)
try! image.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: CommandLine.arguments[1]))
