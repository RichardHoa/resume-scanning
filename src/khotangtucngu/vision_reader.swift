// Apple Vision's text recognition, kept as one process so its model loads once. vision_ocr.py compiles and runs it:
//
//     vision_reader <revision> <language> <language correction, 1 or 0>
//
// It takes an image path per line on stdin and answers one JSON line per image: {"observations": [{"text", "box",
// "confidence"}]}, each box [left, top, right, bottom] as shares of the image from its top left, or {"error"}. A failed
// read never stops it.
import Foundation
import Vision

struct Observation: Encodable {
    let text: String
    let box: [Double]
    let confidence: Float
}

struct Answer: Encodable {
    var observations: [Observation]? = nil
    var error: String? = nil
}

func read(_ path: String, revision: Int, language: String, correction: Bool) throws -> [Observation] {
    let request = VNRecognizeTextRequest()
    request.revision = revision
    request.recognitionLevel = .accurate
    request.recognitionLanguages = [language]
    request.usesLanguageCorrection = correction
    try VNImageRequestHandler(url: URL(fileURLWithPath: path), options: [:]).perform([request])
    return (request.results ?? []).compactMap { observation in
        guard let best = observation.topCandidates(1).first else { return nil }
        // Vision's boxes are shares of the image from its bottom left
        let box = observation.boundingBox
        return Observation(text: best.string, box: [box.minX, 1 - box.maxY, box.maxX, 1 - box.minY].map { Double($0) },
                           confidence: best.confidence)
    }
}

func answer(_ path: String, revision: Int, language: String, correction: Bool) -> Data {
    var answer = Answer()
    do {
        answer.observations = try read(path, revision: revision, language: language, correction: correction)
    } catch {
        answer.error = "\(error)"
    }
    return (try? JSONEncoder().encode(answer)) ?? Data("{\"error\":\"the answer could not be encoded\"}".utf8)
}

let arguments = CommandLine.arguments
guard arguments.count == 4, let revision = Int(arguments[1]) else {
    FileHandle.standardError.write(Data("usage: vision_reader <revision> <language> <1 or 0>\n".utf8))
    exit(2)
}
while let path = readLine() {
    autoreleasepool {
        let line = answer(path, revision: revision, language: arguments[2], correction: arguments[3] == "1")
        FileHandle.standardOutput.write(line + Data("\n".utf8))
    }
}
