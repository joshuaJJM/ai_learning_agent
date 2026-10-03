import XCTest

final class HaoXueUITests: XCTestCase {
    /// Any wrong-question row, whatever the backend's current question numbers
    /// happen to be. Live rows look like「第 7 题 · 已知函数…」.
    private func firstWrongQuestionRow(_ app: XCUIApplication) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label MATCHES %@", "第 [0-9]+ 题.*")).firstMatch
    }

    @MainActor
    func testLiveKnowledgeFromHomeOverviewAndWrongQuestion() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        let pointName = "利用导数判断函数单调性与单调区间"

        app.launch()
        let homePoint = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", pointName)).firstMatch
        XCTAssertTrue(homePoint.waitForExistence(timeout: 20))
        homePoint.tap()
        XCTAssertTrue(app.navigationBars["知识点详情"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts[pointName].exists)
        XCTAssertTrue(app.staticTexts["学习证据"].exists)
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "继续学习")).firstMatch.exists)

        app.terminate()
        app.launch()
        app.tabBars.buttons["学习"].tap()
        app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "知识掌握与补弱")).firstMatch.tap()
        XCTAssertTrue(app.navigationBars["知识状态"].waitForExistence(timeout: 15))
        let overviewPoint = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", pointName)).firstMatch
        XCTAssertTrue(overviewPoint.waitForExistence(timeout: 15))
        overviewPoint.tap()
        XCTAssertTrue(app.navigationBars["知识点详情"].waitForExistence(timeout: 15))

        app.terminate()
        app.launch()
        app.tabBars.buttons["学习"].tap()
        let wrong = firstWrongQuestionRow(app)
        guard wrong.waitForExistence(timeout: 20) else {
            // The wrong-question list is live data: it is legitimately empty for
            // a demo user who has no mistakes yet. Skip instead of asserting a
            // particular question number that only exists in seeded data.
            throw XCTSkip("线上 Demo 用户当前没有错题，跳过依赖错题数据的断言")
        }
        wrong.tap()
        XCTAssertTrue(app.navigationBars["错题详情"].waitForExistence(timeout: 15))
        // Every wrong question links to the knowledge point it belongs to.
        let knowledgeLink = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "导数")).firstMatch
        if knowledgeLink.exists {
            knowledgeLink.tap()
            XCTAssertTrue(app.navigationBars["知识点详情"].waitForExistence(timeout: 15))
        }
    }

    @MainActor
    func testLiveWrongQuestionFromLearningAndHome() throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["学习"].tap()
        let firstWrong = firstWrongQuestionRow(app)
        guard firstWrong.waitForExistence(timeout: 20) else {
            throw XCTSkip("线上 Demo 用户当前没有错题，跳过依赖错题数据的断言")
        }
        firstWrong.tap()
        XCTAssertTrue(app.navigationBars["错题详情"].waitForExistence(timeout: 15))
        // Structural assertions only: the error label and the correct answer are
        // whatever the backend currently returns, not a fixed fixture string.
        XCTAssertTrue(app.staticTexts["你的答案"].exists)
        XCTAssertTrue(app.staticTexts["正确答案"].exists)
        XCTAssertTrue(app.buttons["针对这个问题学习"].exists)
        app.buttons["关闭"].tap()
        app.tabBars.buttons["首页"].tap()
        // Home keeps its own 最近错题 list; match any wrong-question row there too.
        let homeWrong = firstWrongQuestionRow(app)
        XCTAssertTrue(homeWrong.waitForExistence(timeout: 20))
        homeWrong.tap()
        XCTAssertTrue(app.navigationBars["错题详情"].waitForExistence(timeout: 15))
    }

    @MainActor
    func testFreshScannerOpens() {
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["扫描"].tap()
        app.buttons["扫描文档"].tap()
        XCTAssertTrue(app.buttons["Cancel"].waitForExistence(timeout: 5))
        app.buttons["Cancel"].tap()
    }
    @MainActor
    func testPhotoPickerCanOpenScannerImmediately() {
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["扫描"].tap()
        app.buttons["从照片选择"].tap()
        let firstPhoto = app.images.matching(identifier: "PXGGridLayout-Info").firstMatch
        XCTAssertTrue(firstPhoto.waitForExistence(timeout: 30))
        firstPhoto.tap()
        app.buttons["完成"].tap()
        XCTAssertTrue(app.staticTexts["已扫描 1 页"].waitForExistence(timeout: 15))
        app.buttons["上传更多"].tap()
        app.buttons["再次扫描"].tap()
        XCTAssertTrue(app.buttons["Cancel"].waitForExistence(timeout: 5))
        app.buttons["Cancel"].tap()
        XCTAssertTrue(app.staticTexts["已扫描 1 页"].exists)
    }

    @MainActor
    func testPhotoPickerCanAddMorePhotosAndDelete() {
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["扫描"].tap()
        app.buttons["从照片选择"].tap()
        let firstPhoto = app.images.matching(identifier: "PXGGridLayout-Info").firstMatch
        XCTAssertTrue(firstPhoto.waitForExistence(timeout: 30))
        firstPhoto.tap()
        app.buttons["完成"].tap()
        XCTAssertTrue(app.staticTexts["已扫描 1 页"].waitForExistence(timeout: 15))
        app.buttons["上传更多"].tap()
        app.buttons["从照片选择"].tap()
        XCTAssertTrue(firstPhoto.waitForExistence(timeout: 30))
        firstPhoto.tap()
        app.buttons["完成"].tap()
        XCTAssertTrue(app.staticTexts["已扫描 2 页"].waitForExistence(timeout: 15))
        app.buttons["删除当前页"].tap()
        XCTAssertTrue(app.staticTexts["已扫描 1 页"].exists)
    }
    @MainActor
    func testMockLearningUpdatesHomeAndStudy() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments.append("-useMockTutor")
        app.launch()
        XCTAssertTrue(app.staticTexts["导数与函数单调性"].waitForExistence(timeout: 5))
        app.buttons["开始下一步学习"].tap()
        XCTAssertFalse(app.tabBars.firstMatch.isHittable)
        XCTAssertFalse(app.buttons["提交答案"].isEnabled)
        app.buttons["choice-B"].tap()
        app.buttons["choice-A"].tap()
        app.buttons["提交答案"].tap()
        XCTAssertTrue(app.staticTexts["回答正确"].exists)
        XCTAssertFalse(app.buttons["choice-B"].isEnabled)
        app.buttons["草稿本"].tap()
        XCTAssertTrue(app.navigationBars["草稿本"].waitForExistence(timeout: 5))
        app.buttons["橡皮"].tap()
        app.buttons["笔"].tap()
        app.buttons["完成"].tap()
        app.buttons["下一题"].tap()
        XCTAssertTrue(app.staticTexts["课程进度 · 2 / 3"].waitForExistence(timeout: 5))
        app.buttons["choice-A"].tap()
        app.buttons["提交答案"].tap()
        XCTAssertTrue(app.staticTexts["回答错误"].exists)
        XCTAssertTrue(app.staticTexts["导数为负表示 x 增加时函数值减小，所以函数单调递减。"].exists)
        app.buttons["下一题"].tap()
        XCTAssertTrue(app.staticTexts["课程进度 · 3 / 3"].waitForExistence(timeout: 5))
        app.buttons["choice-C"].tap()
        app.buttons["提交答案"].tap()
        app.buttons["下一题"].tap()
        XCTAssertTrue(app.staticTexts["43% → 51%"].exists)
        app.buttons["完成学习"].tap()
        XCTAssertTrue(app.staticTexts["巩固导数与单调性"].exists)
        app.tabBars.buttons["学习"].tap()
        XCTAssertTrue(app.staticTexts["51%"].exists)
        // Mock E2E：Tutor 之后进入 Practice，提交 → 完成 → 学习状态更新提示。
        app.buttons["start-practice"].tap()
        XCTAssertTrue(app.staticTexts["practice-question-stem"].waitForExistence(timeout: 10))
        app.buttons["choice-A"].tap()
        app.buttons["practice-submit-answer"].tap()
        XCTAssertTrue(app.staticTexts["practice-result-correctness"].waitForExistence(timeout: 10))
        app.buttons["practice-next-question"].tap()
        XCTAssertTrue(app.staticTexts["practice-progress"].waitForExistence(timeout: 5))
        app.buttons["choice-B"].tap()
        app.buttons["practice-submit-answer"].tap()
        let finishPractice = app.buttons["practice-finish"]
        XCTAssertTrue(finishPractice.waitForExistence(timeout: 10))
        finishPractice.tap()
        XCTAssertTrue(app.staticTexts["practice-completion-notice"].waitForExistence(timeout: 10))
        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts["导数与函数单调性"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testMockPracticeSessionShowsBackendQuestionAndEnablesSubmit() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments.append("-useMockTutor")
        app.launch()
        app.tabBars.buttons["学习"].tap()
        let start = app.buttons["start-practice"]
        XCTAssertTrue(start.waitForExistence(timeout: 10))
        start.tap()

        // 真实 backend 形状的题目与选项：题干、A-D 全部来自服务器 payload。
        let stem = app.staticTexts["practice-question-stem"]
        XCTAssertTrue(stem.waitForExistence(timeout: 10))
        XCTAssertEqual(stem.label, "在一个区间内 f′(x) > 0，函数有什么性质？")
        XCTAssertTrue(app.staticTexts["practice-progress"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["practice-progress"].label.hasPrefix("第 1 /"))
        for key in ["A", "B", "C", "D"] {
            XCTAssertTrue(app.buttons["choice-\(key)"].exists)
        }

        let submit = app.buttons["practice-submit-answer"]
        XCTAssertTrue(submit.exists)
        XCTAssertFalse(submit.isEnabled)
        app.buttons["choice-B"].tap()
        XCTAssertTrue(submit.isEnabled)
        // 改选只替换本地选择，不产生任何判定。
        app.buttons["choice-C"].tap()
        XCTAssertTrue(submit.isEnabled)
        XCTAssertFalse(app.staticTexts["回答正确"].exists)
        XCTAssertFalse(app.staticTexts["回答错误"].exists)

        // 提交走 provider（mock fixture），结果与解析全部来自 server-shaped response。
        submit.tap()
        XCTAssertTrue(app.staticTexts["回答正确"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["正确答案"].exists)
        XCTAssertTrue(app.staticTexts["导数为正，函数在该区间单调递增。"].exists)
        XCTAssertTrue(app.staticTexts["practice-result-progress"]
            .label.contains("已完成 1 / 2"))
        // 结果页不自动跳题，学生主动点下一题。
        let next = app.buttons["practice-next-question"]
        XCTAssertTrue(next.waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["f′(x) < 0 时，函数在该区间的变化是什么？"].exists)
        next.tap()
        XCTAssertTrue(app.staticTexts["f′(x) < 0 时，函数在该区间的变化是什么？"]
            .waitForExistence(timeout: 5))
        XCTAssertEqual(app.staticTexts["practice-progress"].label, "第 2 / 2 题")
        XCTAssertFalse(app.buttons["practice-submit-answer"].isEnabled)

        app.buttons["草稿本"].tap()
        XCTAssertTrue(app.navigationBars["草稿本"].waitForExistence(timeout: 5))
        app.buttons["完成"].tap()
        XCTAssertTrue(app.buttons["practice-submit-answer"].waitForExistence(timeout: 5))

        // 最后一题：提交 → 完成练习 → 回到学习面并出现完成提示。
        app.buttons["choice-B"].tap()
        app.buttons["practice-submit-answer"].tap()
        let finish = app.buttons["practice-finish"]
        XCTAssertTrue(finish.waitForExistence(timeout: 10))
        finish.tap()
        let notice = app.staticTexts["practice-completion-notice"]
        XCTAssertTrue(notice.waitForExistence(timeout: 10))
        XCTAssertEqual(notice.label, "练习完成 · 学习状态已更新")
        // 关闭提示后仍停留在学习面，练习入口还在。
        app.buttons["关闭提示"].tap()
        XCTAssertTrue(app.buttons["start-practice"].waitForExistence(timeout: 5))
        // 完成后的 identity 已清理：再进入是新 session（第 1 题），不是恢复已完成会话。
        app.buttons["start-practice"].tap()
        XCTAssertEqual(app.staticTexts["practice-progress"].label, "第 1 / 2 题")
        XCTAssertFalse(app.buttons["practice-submit-answer"].isEnabled)
        app.buttons["关闭练习"].tap()
    }

    @MainActor
    func testLivePracticeSessionShowsBackendQuestion() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["学习"].tap()
        let start = app.buttons["start-practice"]
        XCTAssertTrue(start.waitForExistence(timeout: 20))
        start.tap()

        // Live 后端：题干与 A-D 都来自服务器，本地不做任何判定。
        let stem = app.staticTexts["practice-question-stem"]
        XCTAssertTrue(stem.waitForExistence(timeout: 30))
        XCTAssertFalse(stem.label.isEmpty)
        XCTAssertTrue(app.buttons["choice-A"].exists)
        XCTAssertTrue(app.staticTexts["practice-progress"].label.hasPrefix("第 1 /"))
        let submit = app.buttons["practice-submit-answer"]
        XCTAssertTrue(submit.exists)
        XCTAssertFalse(submit.isEnabled)
        app.buttons["choice-A"].tap()
        XCTAssertTrue(submit.isEnabled)
        XCTAssertFalse(app.staticTexts["回答正确"].exists)
        XCTAssertFalse(app.staticTexts["回答错误"].exists)
        // Phase 6C 才提交答案；6B 只验证“坐到题前并完成选择”。
        app.buttons["关闭练习"].tap()
    }

    @MainActor
    func testScratchpadDrawingPersistsThenClearsForNextQuestion() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments.append("-useMockTutor")
        app.launch()
        app.buttons["开始下一步学习"].tap()
        app.buttons["草稿本"].tap()
        let canvas = app.scrollViews["scratchpadCanvas"]
        XCTAssertTrue(canvas.waitForExistence(timeout: 5))
        let start = canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.3, dy: 0.3))
        let end = canvas.coordinate(withNormalizedOffset: CGVector(dx: 0.6, dy: 0.5))
        start.press(forDuration: 0.1, thenDragTo: end)
        XCTAssertTrue(app.buttons["清空"].isEnabled)
        app.buttons["完成"].tap()
        app.buttons["草稿本"].tap()
        XCTAssertTrue(app.buttons["清空"].isEnabled)
        app.buttons["清空"].tap()
        let confirmation = app.alerts["清空草稿？"]
        XCTAssertTrue(confirmation.waitForExistence(timeout: 5))
        confirmation.buttons["取消"].tap()
        XCTAssertTrue(app.buttons["清空"].isEnabled)
        app.buttons["清空"].tap()
        app.alerts["清空草稿？"].buttons["清空"].tap()
        XCTAssertFalse(app.buttons["清空"].isEnabled)
        start.press(forDuration: 0.1, thenDragTo: end)
        XCTAssertTrue(app.buttons["清空"].isEnabled)
        app.buttons["完成"].tap()
        app.buttons["choice-A"].tap()
        app.buttons["提交答案"].tap()
        app.buttons["下一题"].tap()
        app.buttons["草稿本"].tap()
        XCTAssertFalse(app.buttons["清空"].isEnabled)
    }

    @MainActor
    func testFourTabsAndMockScanResult() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["首页"].exists)
        XCTAssertTrue(app.tabBars.buttons["扫描"].exists)
        XCTAssertTrue(app.tabBars.buttons["学习"].exists)
        XCTAssertTrue(app.tabBars.buttons["设置"].exists)
        app.tabBars.buttons["扫描"].tap()
        XCTAssertTrue(app.staticTexts["从一页作业开始"].exists)
        app.buttons["扫描设置"].tap()
        app.buttons["切换演示模式"].tap()
        app.buttons["添加演示页面"].tap()
        XCTAssertTrue(app.staticTexts["已扫描 1 页"].exists)
        app.buttons["上传更多"].tap()
        app.buttons["添加演示页面"].tap()
        XCTAssertTrue(app.staticTexts["已扫描 2 页"].exists)
        app.buttons["删除当前页"].tap()
        XCTAssertTrue(app.staticTexts["已扫描 1 页"].exists)
        app.buttons["上传更多"].tap()
        app.buttons["添加演示页面"].tap()
        XCTAssertTrue(app.staticTexts["已扫描 2 页"].exists)
        app.buttons["开始分析"].tap()
        XCTAssertTrue(app.buttons["查看分析结果"].waitForExistence(timeout: 30))
        app.buttons["查看分析结果"].tap()
        XCTAssertTrue(app.buttons["开始学习"].exists)
        app.tabBars.buttons["设置"].tap()
        XCTAssertTrue(app.navigationBars["设置"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["关于好学"].exists)
    }

    /// The real "fixed sample" upload path: pick photos from the library, let the
    /// app prepare and upload them, and wait for the live backend to finish the
    /// analysis. Opt in with HAOXUE_LIVE_UPLOAD_TEST=1 because a live VLM run
    /// takes minutes; it stays out of the default suite.
    @MainActor
    func testFixedSampleUploadCompletesRealAnalysis() throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["HAOXUE_LIVE_UPLOAD_TEST"] == "1",
                          "设置 HAOXUE_LIVE_UPLOAD_TEST=1 才运行真实上传（需要几分钟 AI 时间）")
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["扫描"].tap()
        app.buttons["从照片选择"].tap()

        let photos = app.images.matching(identifier: "PXGGridLayout-Info")
        XCTAssertTrue(photos.firstMatch.waitForExistence(timeout: 30))
        let selected = min(photos.count, 3)
        XCTAssertGreaterThan(selected, 0)
        for index in 0..<selected { photos.element(boundBy: index).tap() }
        app.buttons["完成"].tap()

        XCTAssertTrue(app.staticTexts["已扫描 \(selected) 页"].waitForExistence(timeout: 30))
        app.buttons["开始分析"].tap()
        // Live VLM: the whole chain can take several minutes.
        XCTAssertTrue(app.navigationBars["本次分析"].waitForExistence(timeout: 900))
        XCTAssertTrue(app.staticTexts["本次分析"].exists)
        // The result must be a real server payload, never the mock preview.
        XCTAssertFalse(app.staticTexts["分析结果预览"].exists)
    }
}
