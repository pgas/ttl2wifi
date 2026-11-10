#pragma once

#include <string>
#include <vector>

namespace ttl2wifi {

struct NavLink {
    std::string url;
    std::string label;
    std::string item_type; // e.g. "0" (text), "1" (menu), "7" (search), "8" (telnet), "gemini"
};

class NavHistory {
public:
    void clear_links() {
        links_.clear();
    }

    void set_page(const std::string& url, bool push_history = true) {
        if (push_history && !current_url_.empty() && current_url_ != url) {
            history_.push_back(current_url_);
            if (history_.size() > 20) {
                history_.erase(history_.begin());
            }
        }
        current_url_ = url;
        clear_links();
    }

    size_t add_link(const std::string& url, const std::string& label, const std::string& type) {
        links_.push_back({url, label, type});
        return links_.size();
    }

    const std::vector<NavLink>& links() const { return links_; }
    const std::string& current_url() const { return current_url_; }
    bool has_history() const { return !history_.empty(); }

    std::string pop_history() {
        if (history_.empty()) return "";
        std::string prev = history_.back();
        history_.pop_back();
        return prev;
    }

    const NavLink* get_link(size_t index_1_based) const {
        if (index_1_based >= 1 && index_1_based <= links_.size()) {
            return &links_[index_1_based - 1];
        }
        return nullptr;
    }

private:
    std::string current_url_;
    std::vector<NavLink> links_;
    std::vector<std::string> history_;
};

} // namespace ttl2wifi

