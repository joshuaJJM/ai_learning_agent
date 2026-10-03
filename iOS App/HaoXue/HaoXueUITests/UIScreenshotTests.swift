import XCTest

/// Phase 9A visual QA capture. These tests do not assert product behaviour —
/// they walk the demo surfaces and file one screenshot per view into the
/// result bundle, so `UI图片` can be regenerated on demand:
///
/// ```
/// xcodebuild test -scheme HaoXue -destination 'platform=iOS Simulator,name=iPhone 18 Pro' \
///   -only-testing:HaoXueUITests/UIScreenshotTests -resultBundlePath /tmp/haoxue-ui.xcresult
/// xcrun xcresulttool export attachments --path /tmp/haoxue-ui.xcresult --output-path /tmp/haoxue-ui
/// ```
final class UIScreenshotTests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication()
    }

    override func tearDown() {
        app = nil
    }

    // MARK: - Helpers

    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    @discardableResult
    private func wait(_ element: XCUIElement, _ timeout: TimeInterval = 25,
                      _ message: String? = nil) -> Bool {
        let appeared = element.waitForExistence(timeout: timeout)
        XCTAssertTrue(appeared, message ?? "等待元素出现超时：\(element)")
        return appeared
    }

    private func tapTab(_ name: String) {
        let tab = app.tabBars.buttons[name]
        wait(tab)
        tab.tap()
    }

    private func selectPhotos(_ count: Int) {
        let photos = app.images.matching(identifier: "PXGGridLayout-Info")
        wait(photos.firstMatch, 40)
        for index in 0..<min(count, photos.count) {
            photos.element(boundBy: index).tap()
        }
        app.buttons["完成"].tap()
    }

    /// Live backend rows are「第 7 题 · 已知函数…」and the numbering changes
    /// with the data, so never assert a specific question number here.
    private func firstWrongQuestionRow() -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label MATCHES %@", "第 [0-9]+ 题.*")).firstMatch
    }

    // MARK: - 1. Live demo path

    @MainActor
    func testCaptureLiveDemoPath() throws {
        app.launch()

        // 01 首页
        wait(app.staticTexts["下一步"])
        capture("01-home")

        // 02 学习面（错题 + 入口）
        tapTab("学习")
        wait(app.staticTexts["错题"])
        capture("02-learn-wrong-questions")

        // 03 知识点总览
        app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "知识掌握与补弱")).firstMatch.tap()
        wait(app.navigationBars["知识状态"])
        capture("03-knowledge-overview")

        // 04 知识点详情
        let knowledgeRow = app.buttons
            .matching(NSPredicate(format: "label CONTAINS %@", "条学习证据")).firstMatch
        if knowledgeRow.waitForExistence(timeout: 20) {
            knowledgeRow.tap()
            wait(app.navigationBars["知识点详情"])
            capture("04-knowledge-detail")
            app.buttons["关闭"].tap()
            wait(app.navigationBars["知识状态"])
        }
        app.buttons["关闭"].tap()
        wait(app.staticTexts["错题"])

        // 05 错题详情
        let wrong = firstWrongQuestionRow()
        if wrong.waitForExistence(timeout: 25) {
            wrong.tap()
            wait(app.navigationBars["错题详情"])
            capture("05-wrong-question-detail")
            app.buttons["关闭"].tap()
        }

        // 06 扫描空状态
        tapTab("扫描")
        wait(app.staticTexts["从一页作业开始"])
        capture("06-scan-empty")

        // 07 多页预览
        app.buttons["从照片选择"].tap()
        selectPhotos(2)
        wait(app.staticTexts["已扫描 2 页"])
        capture("07-scan-pages")

        // 08 扫描历史
        app.buttons["scan-history-button"].tap()
        wait(app.navigationBars["历史记录"])
        capture("08-scan-history")

        // 09 历史分析结果（真实后端 payload）
        let batchRows = app.buttons.matching(
            NSPredicate(format: "identifier BEGINSWITH %@", "history-batch-"))
        _ = batchRows.firstMatch.waitForExistence(timeout: 30)
        // A finished batch renders its counts; processing ones are disabled.
        let finished = batchRows.allElementsBoundByIndex.filter {
            $0.isEnabled && $0.label.contains("道题")
        }
        try XCTSkipIf(finished.isEmpty, "线上暂时没有已完成的历史批次，跳过分析结果截图")
        var opened = false
        for row in finished where !opened {
            row.tap()
            opened = app.navigationBars["本次分析"].waitForExistence(timeout: 45)
        }
        XCTAssertTrue(opened, "没有成功打开任何历史批次的分析结果")
        capture("09-analysis-result")
        app.swipeUp()
        capture("10-analysis-result-detail")
    }

    // MARK: - 2. Live tutor session

    @MainActor
    func testCaptureLiveTutorAndScratchpad() throws {
        app.launch()

        let start = app.buttons["开始学习"]
        guard wait(start, 30, "首页没有可用的下一步学习入口") else { return }
        start.tap()
        wait(app.buttons["草稿本"], 60)
        _ = app.staticTexts["理解检查"].waitForExistence(timeout: 20)
        capture("11-tutor-live")

        app.buttons["草稿本"].tap()
        wait(app.navigationBars["草稿本"])
        let canvas = app.scrollViews["scratchpadCanvas"]
        if canvas.waitForExistence(timeout: 5) {
            canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.28, dy: 0.24))
                .press(forDuration: 0.05,
                       thenDragTo: canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.66, dy: 0.38)))
            canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.30, dy: 0.44))
                .press(forDuration: 0.05,
                       thenDragTo: canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.58, dy: 0.30)))
        }
        capture("12-scratchpad")
        app.buttons["完成"].tap()
        wait(app.buttons["草稿本"])
        app.buttons["关闭课程"].tap()
    }

    // MARK: - 3. Mock learning surface (fixed, offline fixtures)

    @MainActor
    func testCaptureMockLearningSurfaces() {
        app.launchArguments.append("-useMockTutor")
        app.launch()

        wait(app.staticTexts["下一步"])
        capture("13-home-mock")

        // Tutor：题目 → 作答 → 完成
        app.buttons["开始下一步学习"].tap()
        wait(app.buttons["choice-A"], 15)
        capture("14-tutor-question")
        app.buttons["choice-B"].tap()
        capture("15-tutor-choice-selected")
        app.buttons["choice-A"].tap()
        app.buttons["提交答案"].tap()
        wait(app.staticTexts["回答正确"])
        capture("16-tutor-answered")
        app.buttons["下一题"].tap()
        app.buttons["choice-A"].tap()
        app.buttons["提交答案"].tap()
        wait(app.staticTexts["回答错误"])
        capture("17-tutor-remedial")
        app.buttons["下一题"].tap()
        app.buttons["choice-C"].tap()
        app.buttons["提交答案"].tap()
        app.buttons["下一题"].tap()
        wait(app.staticTexts["43% → 51%"])
        capture("18-tutor-completion")
        app.buttons["完成学习"].tap()

        // 学习面 + Practice
        tapTab("学习")
        wait(app.staticTexts["导数与单调性"])
        capture("19-learn-mock")
        app.buttons["start-practice"].tap()
        wait(app.staticTexts["practice-question-stem"], 20)
        capture("20-practice-question")
        app.buttons["choice-A"].tap()
        capture("21-practice-choice-selected")
        app.buttons["practice-submit-answer"].tap()
        wait(app.staticTexts["practice-result-correctness"], 20)
        capture("22-practice-result")
        app.buttons["practice-next-question"].tap()
        wait(app.staticTexts["practice-progress"], 10)
        app.buttons["choice-B"].tap()
        app.buttons["practice-submit-answer"].tap()
        wait(app.buttons["practice-finish"], 20)
        capture("23-practice-completion")
        app.buttons["practice-finish"].tap()
        wait(app.staticTexts["practice-completion-notice"], 20)
        capture("24-learning-state-updated")
    }

    // MARK: - 4. Scan flow (mock analysis, real photos)

    @MainActor
    func testCaptureScanReviewAndProgress() {
        app.launch()
        tapTab("扫描")
        wait(app.staticTexts["从一页作业开始"])

        app.buttons["从照片选择"].tap()
        selectPhotos(3)
        wait(app.staticTexts["已扫描 3 页"])
        capture("25-scan-review-controls")

        // Mock analysis keeps the live VLM out of the screenshot run.
        app.buttons["扫描设置"].tap()
        app.buttons["切换演示模式"].tap()
        app.buttons["开始分析"].tap()
        Thread.sleep(forTimeInterval: 3)
        // The progress card sits under the page carousel: bring it into frame.
        app.swipeUp()
        Thread.sleep(forTimeInterval: 0.5)
        capture("26-analysis-progress")
        wait(app.buttons["查看分析结果"], 30)
        capture("27-analysis-completed")
    }

    // MARK: - 5. Settings & commercial demo

    @MainActor
    func testCaptureSettingsSurfaces() {
        app.launch()
        tapTab("设置")
        wait(app.navigationBars["设置"])
        capture("28-settings")

        app.buttons["图书与题库"].tap()
        wait(app.navigationBars["图书与题库"], 30)
        capture("29-book-store")
        let firstBook = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "道练习")).firstMatch
        if firstBook.waitForExistence(timeout: 20) {
            firstBook.tap()
            wait(app.navigationBars["图书详情"])
            capture("30-book-detail")
            app.swipeUp()
            capture("31-book-unlock")
            app.navigationBars.buttons["图书与题库"].tap()
        }
        app.navigationBars.buttons["设置"].tap()

        app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "好学计划")).firstMatch.tap()
        wait(app.navigationBars["好学计划"])
        capture("32-subscription")
        app.navigationBars.buttons["设置"].tap()

        app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "学习额度")).firstMatch.tap()
        wait(app.navigationBars["学习额度"])
        capture("33-credits")
        app.navigationBars.buttons["设置"].tap()

        app.buttons["邀请同学"].tap()
        wait(app.navigationBars["邀请同学"])
        capture("34-invite")
        app.navigationBars.buttons["设置"].tap()

        app.buttons["数据与隐私"].tap()
        wait(app.navigationBars["数据与隐私"])
        capture("35-privacy")
        app.navigationBars.buttons["设置"].tap()

        app.buttons["专注模式"].tap()
        wait(app.navigationBars["学习专注"])
        capture("36-focus")
        app.navigationBars.buttons["设置"].tap()

        app.buttons["关于好学"].tap()
        wait(app.navigationBars["关于好学"])
        capture("37-about")
    }
}
