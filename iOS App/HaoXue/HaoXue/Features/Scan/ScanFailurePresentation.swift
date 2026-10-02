struct ScanFailurePresentation {
    let code: String?

    var requiresNewScan: Bool {
        code == "INVALID_IMAGE" || code == "QUESTION_NOT_RECOGNIZED"
    }

    var message: String {
        switch code {
        case "INVALID_IMAGE": "图片似乎无法使用，请重新扫描清晰完整的页面。"
        case "QUESTION_NOT_RECOGNIZED": "没有从图片中识别出题目，请换一张清晰完整的作业照片。"
        case "VLM_TIMEOUT": "服务器分析超时，请再试一次。"
        case "NETWORK_ERROR": "连接暂时中断，重新尝试会继续当前任务。"
        case "ANALYSIS_FAILED": "服务器未能完成分析，请再试一次。"
        case .some(let code): "分析未完成（\(code)），请再试一次。"
        case .none: "分析未完成，请再试一次。"
        }
    }
}
