// Local image helper for the Lupin image editor (macOS Vision and ImageIO).
//   image_helper cutout <input image> <output png>   remove the background
//   image_helper orient <input image> <output image> bake the EXIF orientation into the pixels
// Exit codes: 0 ok, 2 bad usage, 3 cannot read image, 4 no foreground found (cutout),
// 5 Vision/ImageIO failed or unavailable, 10 nothing to do (orient: already upright).
import Foundation
import Vision
import CoreImage
import ImageIO
import UniformTypeIdentifiers

let args = CommandLine.arguments
guard args.count == 4 else { exit(2) }
let mode = args[1]
let inURL = URL(fileURLWithPath: args[2])
let outURL = URL(fileURLWithPath: args[3])

func writeImage(_ image: CIImage, type: String, quality: Double?) -> Bool {
    let context = CIContext()
    guard let cg = context.createCGImage(image, from: image.extent),
          let dest = CGImageDestinationCreateWithURL(outURL as CFURL, type as CFString, 1, nil)
    else { return false }
    var options: [CFString: Any] = [:]
    if let quality = quality { options[kCGImageDestinationLossyCompressionQuality] = quality }
    CGImageDestinationAddImage(dest, cg, options as CFDictionary)
    return CGImageDestinationFinalize(dest)
}

switch mode {
case "cutout":
    guard let image = CIImage(contentsOf: inURL, options: [.applyOrientationProperty: true]) else { exit(3) }
    guard #available(macOS 14.0, *) else { exit(5) }
    let request = VNGenerateForegroundInstanceMaskRequest()
    let handler = VNImageRequestHandler(ciImage: image, options: [:])
    do {
        try handler.perform([request])
        guard let result = request.results?.first, !result.allInstances.isEmpty else { exit(4) }
        let buffer = try result.generateMaskedImage(
            ofInstances: result.allInstances, from: handler, croppedToInstancesExtent: false)
        guard writeImage(CIImage(cvPixelBuffer: buffer), type: UTType.png.identifier, quality: nil) else { exit(5) }
    } catch {
        exit(5)
    }
case "orient":
    guard let source = CGImageSourceCreateWithURL(inURL as CFURL, nil),
          let props = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any]
    else { exit(3) }
    let orientation = (props[kCGImagePropertyOrientation] as? NSNumber)?.intValue ?? 1
    if orientation == 1 { exit(10) }
    guard let image = CIImage(contentsOf: inURL, options: [.applyOrientationProperty: true]) else { exit(3) }
    let type = (CGImageSourceGetType(source) as String?) ?? UTType.jpeg.identifier
    let lossy = type == UTType.jpeg.identifier || type == "public.heic"
    guard writeImage(image, type: type, quality: lossy ? 0.95 : nil) else { exit(5) }
default:
    exit(2)
}
