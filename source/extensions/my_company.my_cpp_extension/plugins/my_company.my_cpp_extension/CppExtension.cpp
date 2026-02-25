/*
 * SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES.
 * All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#define CARB_EXPORTS

#include <carb/PluginUtils.h>
#include <carb/logging/Log.h>
#include <carb/eventdispatcher/IEventDispatcher.h>
#include <carb/events/IEvents.h>
#include <carb/events/EventsUtils.h>

#include <omni/ext/IExt.h>
#include <omni/kit/IApp.h>

#include <memory>


#define EXTENSION_NAME "my_company.my_cpp_extension.plugin"

// 대략 60 FPS 기준으로 10초 동안 약 600번 업데이트가 발생한다고 가정.
// 이 값(kUpdatesPer10Seconds)을 기준으로 10초마다 한 번씩 로그를 남긴다.
static const int kUpdatesPer10Seconds = 600;

using namespace carb;

// 플러그인 구현 정보(Plugin Implementation Descriptor):
// - 네이티브 플러그인 이름, 설명, 작성자, 버전, 핫 리로드 지원 여부 등을 기술한다.
// - Carbonite/Kit 이 이 정보를 기반으로 플러그인을 등록하고 관리한다.
const struct carb::PluginImplDesc kPluginImpl = {
    EXTENSION_NAME,  // 플러그인 이름(전역에서 유일해야 함, 예: "carb.dictionary.plugin")
    "Example of a native plugin extension.",  // 디버깅/툴에서 보일 설명 문자열
    "NVIDIA",  // 작성자
    carb::PluginHotReload::eDisabled,
    "dev"  // Build version of the plugin.
};

// 이 플러그인이 필요로 하는 의존성:
// - omni::kit::IApp: Kit 애플리케이션 인터페이스 (런타임 환경)
// - carb::logging::ILogging: CARB_LOG_* 매크로가 사용하는 로깅 인터페이스
CARB_PLUGIN_IMPL_DEPS(omni::kit::IApp, carb::logging::ILogging)


class NativeExtensionExample : public omni::ext::IExt
{
public:
    // 확장이 시작될 때 호출되는 함수.
    // 전역 업데이트 이벤트 스트림을 구독하고, 약 10초마다 로그를 남기는 카운터를 설정한다.
    void onStartup(const char* extId) override
    {
        printf(EXTENSION_NAME ": in onStartup\n");
        // Carbonite 프레임워크에서 전역 이벤트 디스패처 인터페이스를 가져온다.
        auto ed = carb::getCachedInterface<carb::eventdispatcher::IEventDispatcher>();
        m_subscription = ed->observeEvent(
            carb::RStringKey("cpp.example.update"),
            0,
            omni::kit::kGlobalEventUpdate,
            // 이 람다는 전역 업데이트 이벤트가 발생할 때마다(보통 한 프레임마다) 호출된다.
            // 호출될 때마다 카운터를 증가시키고, 마지막 로그 시점 이후로
            // 약 10초 분량의 업데이트가 지나면 로그를 한 번 출력한다.
            [this](const carb::eventdispatcher::Event& e) {
                m_counter++;
                if (m_counter - m_last_print_counter >= kUpdatesPer10Seconds)
                {
                    printf(EXTENSION_NAME ": %d (every 10s)\n", m_counter);
                    CARB_LOG_INFO(EXTENSION_NAME ": %d (every 10s)\n", m_counter);
                    m_last_print_counter = m_counter;
                }
            });
    }

    // 확장이 종료될 때 호출되는 함수.
    // 객체가 파괴되기 전에 이벤트 구독을 반드시 해제하여 안전하게 정리한다.
    void onShutdown() override
    {
        // 이벤트 스트림 구독 해제
        m_subscription.reset();
    }

private:
    int m_counter = 0;                     // 지금까지 처리한 업데이트 이벤트(프레임) 수를 누적하는 카운터.
    int m_last_print_counter = 0;          // 마지막으로 로그를 찍었을 때의 m_counter 값.
    carb::eventdispatcher::ObserverGuard m_subscription;  // 이벤트 구독 수명을 관리하는 RAII 객체.
};


// 플러그인 등록 및 보일러플레이트 코드를 생성하는 매크로.
CARB_PLUGIN_IMPL(kPluginImpl, NativeExtensionExample)

// 이 플러그인이 외부로 내보내는 각 인터페이스 타입마다
// 하나의 fillInterface(InterfaceType&) 함수가 반드시 존재해야 한다.
void fillInterface(NativeExtensionExample& iface)
{
}
