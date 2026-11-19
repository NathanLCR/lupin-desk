// Background removal with macOS Vision. Usage: vision_cutout <input image> <output png>
// Exit codes: 0 ok, 2 bad usage, 3 cannot read image, 4 no foreground found, 5 Vision failed/unavailable.
import Foundation
import Vision
import CoreImage
import ImageIO
import UniformTypeIdentifiers

let args = CommandLine.arguments
guard args.count == 3 else { exit(2) }
let inURL = URL(fileURLWithPath: args[1])
let outURL = URL(fileURLWithPath: args[2])

guard let image = CIImage(contentsOf: inURL, options: [.applyOrientationProperty: true]) else { exit(3) }

guard #available(macOS 14.0, *) else { exit(5) }

let request = VNGenerateForegroundInstanceMaskRequest()
let handler = VNImageRequestHandler(ciImage: image, options: [:])
do {
    try handler.perform([request])
    guard let result = request.results?.first, !result.allInstances.isEmpty else { exit(4) }
    let buffer = try result.generateMaskedImage(
        ofInstances: result.allInstances, from: handler, croppedToInstancesExtent: false)
    let masked = CIImage(cvPixelBuffer: buffer)
    let context = CIContext()
    guard let cg = context.createCGImage(masked, from: masked.extent),
          let dest = CGImageDestinationCreateWithURL(outURL as CFURL, UTType.png.identifier as CFString, 1, nil)
    else { exit(5) }
    CGImageDestinationAddImage(dest, cg, nil)
    guard CGImageDestinationFinalize(dest) else { exit(5) }
} catch {
    exit(5)
}
