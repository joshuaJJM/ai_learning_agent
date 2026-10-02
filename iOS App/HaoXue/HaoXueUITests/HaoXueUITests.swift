import XCTest

final class HaoXueUITests: XCTestCase {
    @MainActor
    func testLiveKnowledgeFromHomeOverviewAndWrongQuestion() {
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
        app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "知识状态")).firstMatch.tap()
        XCTAssertTrue(app.navigationBars["知识状态"].waitForExistence(timeout: 15))
        let overviewPoint = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", pointName)).firstMatch
        XCTAssertTrue(overviewPoint.waitForExistence(timeout: 15))
        overviewPoint.tap()
        XCTAssertTrue(app.navigationBars["知识点详情"].waitForExistence(timeout: 15))

        app.terminate()
        app.launch()
        app.tabBars.buttons["学习"].tap()
        let wrong = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "第 17 题")).firstMatch
        XCTAssertTrue(wrong.waitForExistence(timeout: 20))
        wrong.tap()
        XCTAssertTrue(app.navigationBars["错题详情"].waitForExistence(timeout: 15))
        app.buttons[pointName].tap()
        XCTAssertTrue(app.navigationBars["知识点详情"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts[pointName].exists)
    }

    @MainActor
    func testLiveWrongQuestionFromLearningAndHome() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["学习"].tap()
        let firstWrong = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "第 17 题")).firstMatch
        XCTAssertTrue(firstWrong.waitForExistence(timeout: 20))
        firstWrong.tap()
        XCTAssertTrue(app.navigationBars["错题详情"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["你的答案"].exists)
        XCTAssertTrue(app.staticTexts["正确答案"].exists)
        XCTAssertTrue(app.staticTexts["函数性质转换错误"].exists)
        XCTAssertTrue(app.buttons["针对这个问题学习"].exists)
        app.buttons["关闭"].tap()
        app.tabBars.buttons["首页"].tap()
        let homeWrong = app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "第 17 题")).firstMatch
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
        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts["导数与函数单调性"].waitForExistence(timeout: 5))
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
        XCTAssertTrue(app.staticTexts["扫描可切换真实后端与演示模式"].exists)
    }
}
