import CoreImage
import CoreImage.CIFilterBuiltins
import UIKit

/// A QR code for a phone's camera, with what it opens.
struct PhoneCode: Equatable {
    let title: String
    let link: URL
    let image: UIImage

    init?(title: String, link: URL) {
        let filter = CIFilter.qrCodeGenerator()
        filter.message = Data(link.absoluteString.utf8)
        filter.correctionLevel = "M"
        guard let output = filter.outputImage?.transformed(by: CGAffineTransform(scaleX: 12, y: 12)),
              let cg = CIContext().createCGImage(output, from: output.extent) else { return nil }
        self.title = title.isEmpty ? "Open on your phone" : title
        self.link = link
        image = UIImage(cgImage: cg)
    }

    static func == (a: PhoneCode, b: PhoneCode) -> Bool { a.title == b.title && a.link == b.link }

    /// What the card says under the code.
    var hint: String {
        link.host?.hasSuffix("walmart.com") == true
            ? "Scan with your phone's camera. Walmart opens with the items in your cart; review it and check out there."
            : "Scan with your phone's camera while it is on the home Wi-Fi."
    }
}
