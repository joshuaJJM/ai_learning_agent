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
