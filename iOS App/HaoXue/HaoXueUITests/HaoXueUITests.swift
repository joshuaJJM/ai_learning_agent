import XCTest

final class HaoXueUITests: XCTestCase {
    @MainActor
    func testMockLearningUpdatesHomeAndStudy() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.staticTexts["导数与函数单调性"].waitForExistence(timeout: 5))
        app.buttons["开始下一步学习"].tap()
        XCTAssertFalse(app.tabBars.firstMatch.isHittable)
        app.buttons["选项 A"].tap()
        app.buttons["提交答案"].tap()
        XCTAssertTrue(app.staticTexts["很好。当 f′(x) > 0 时，函数在该区间内单调递增。"].exists)
        app.buttons["继续学习"].tap()
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
    func testFourTabsAndMockScanResult() {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.tabBars.buttons["首页"].exists)
        XCTAssertTrue(app.tabBars.buttons["扫描"].exists)
        XCTAssertTrue(app.tabBars.buttons["学习"].exists)
        XCTAssertTrue(app.tabBars.buttons["设置"].exists)
        app.tabBars.buttons["扫描"].tap()
        XCTAssertTrue(app.staticTexts["已扫描 3 页"].exists)
        app.buttons["查看模拟分析结果"].tap()
        XCTAssertTrue(app.staticTexts["分析完成"].exists)
        XCTAssertTrue(app.buttons["开始学习"].exists)
        app.tabBars.buttons["设置"].tap()
        XCTAssertTrue(app.staticTexts["演示模式 · 本地数据"].exists)
    }
}
